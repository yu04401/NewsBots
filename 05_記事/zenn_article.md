---
title: "毎朝DiscordにAI厳選ITニュースが届くBotをAWS Lambda + Claudeで作った"
emoji: "📰"
type: "tech"
topics: ["aws", "lambda", "python", "discord", "claude"]
published: false
---

## はじめに

毎朝 IT 系ニュースをチェックするのが習慣なのですが、情報源が多すぎて重要な記事を見逃すことが増えていました。RSSリーダーで管理しても未読が溜まるだけ。「誰かが毎朝5件だけ厳選して Discord に届けてくれたら最高なのでは？」と思い、その「誰か」を Claude AI に担ってもらうことにしました。

**作ったもの:**
- 6 つのニュースソースから最大 120 件の記事を自動収集
- Claude AI がエンジニア視点でトップ 5 件を厳選・日本語要約
- 毎朝 6:00 JST に Discord へ自動配信
- AWS のサーバーレス構成で **ランニングコストはほぼゼロ**

![Discordに届いたニュースのスクリーンショット]()
*↑ 毎朝こんな感じで届く*

## システム構成

```
EventBridge Scheduler（毎朝 6:00 JST）
         │
         ▼
  Lambda Function（Python 3.13）
         │
         ├─① SSM Parameter Store からシークレット取得
         ├─② RSS / Hacker News API から記事収集（最大 120 件）
         ├─③ Claude claude-haiku-4-5 でトップ 5 件を厳選・日本語要約
         └─④ Discord Webhook へ Embed 形式で送信
```

**使用技術スタック**

| 用途 | 採用技術 |
|------|---------|
| 実行基盤 | AWS Lambda（Python 3.13） |
| スケジューリング | AWS EventBridge Scheduler |
| シークレット管理 | AWS SSM Parameter Store |
| AI 厳選・要約 | Anthropic Claude claude-haiku-4-5 |
| RSS 取得 | feedparser 6.0.11 |
| HTTP クライアント | httpx 0.28.1 |
| 外部ライブラリ管理 | Lambda Layer |
| 配信先 | Discord Webhook（Embed 形式） |

**ニュースソース一覧**

| ソース | 種別 | 言語 |
|-------|------|------|
| Hacker News | JSON API | 英語 |
| TechCrunch | RSS | 英語 |
| The Verge | RSS | 英語 |
| Zenn トレンド | RSS | 日本語 |
| Qiita トレンド | RSS | 日本語 |
| ITmedia | RSS | 日本語 |

### コストについて

Lambda・EventBridge・SSM は今回の使い方（1日1回・数十秒の実行）では**すべて無料枠内**です。費用が発生するのは Claude API のみで、月あたり **$0.05〜$0.15 程度**です。

:::message
claude-haiku-4-5 は Claude シリーズの中でも最もコストが低いモデルで、今回のような「テキストの分類・要約」タスクに十分な性能を持ちます。
:::

## ディレクトリ構成

```
newsbot/
├── lambda_function.py    # Lambda エントリーポイント（オーケストレーター）
├── ssm_client.py         # SSM からシークレット取得
├── news_fetcher.py       # RSS / Hacker News 記事取得
├── ai_ranker.py          # Claude AI 厳選・要約
├── discord_notifier.py   # Discord Webhook 送信
├── models.py             # dataclass（Article, BotConfig）
├── config.py             # 定数・ニュースソース定義
├── requirements.txt      # 外部ライブラリ（Lambda Layer 用）
├── run_local.py          # ローカル実行スクリプト
└── tests/
    ├── test_news_fetcher.py
    ├── test_ai_ranker.py
    └── test_discord_notifier.py
```

各モジュールの責務を 1 つに絞り、`lambda_function.py` がパイプラインのように順番に呼び出す設計にしています。各モジュールは `list[Article]` か `BotConfig` のやり取りだけを知っており、互いの内部実装に依存しません。

## 実装のポイント

### 1. lambda_function.py はただのオーケストレーター

エントリーポイントは処理の流れを読むだけで済むように、ロジックを一切持たせませんでした。例外は各モジュールから伝播させ、Lambda の失敗ログとして CloudWatch に記録します。

```python
def lambda_handler(event: dict, context: object) -> dict:
    logger.info("[START] NewsBot Lambda started")

    config  = get_config()                       # ① SSM からシークレット取得
    articles = fetch_all_articles()              # ② 全ソースから記事収集
    if len(articles) == 0:
        return {"statusCode": 200, "body": "No articles"}

    ranked = rank_and_summarize(articles, config) # ③ Claude で厳選・要約
    send(ranked, config)                          # ④ Discord へ送信

    logger.info("[END] NewsBot Lambda completed successfully")
    return {"statusCode": 200, "body": json.dumps(f"Sent {len(ranked)} articles")}
```

### 2. データモデルは `@dataclass(slots=True)` で軽量に

記事 1 件を表す `Article` と設定値を束ねる `BotConfig` の 2 つだけを定義しています。`slots=True` を指定すると `__slots__` が自動生成され、通常の dataclass よりメモリ効率が良くなります。120 件分のオブジェクトを扱う今回のケースでは特に有効です。

```python
@dataclass(slots=True)
class Article:
    title:   str
    url:     str
    source:  str
    color:   int        # Discord Embed のカラーコード（ソースごとに色分け）
    summary: str = ""   # Claude が後から書き込む
    rank:    int = 0    # Claude が後から書き込む
```

`summary` と `rank` の初期値を空・0 にしておき、AI 厳選フェーズで直接代入する設計です。`slots=True` の dataclass でも通常の属性代入で問題なく動きます。

### 3. ニュース取得：1 ソースが落ちても止めない

各ソースの取得を個別に `try/except` で囲み、失敗したソースは WARNING ログに記録してスキップします。全ソースが失敗した場合のみ空リストを返し、`lambda_handler` 側で Discord 送信をスキップします。

```python
def fetch_all_articles() -> list[Article]:
    all_articles: list[Article] = []
    seen_urls: set[str] = set()   # URL の重複除去用

    for source in NEWS_SOURCES:
        try:
            articles = _fetch_hackernews(source) if source["type"] == "hackernews" \
                       else _fetch_rss(source)
            # 同じ URL が複数ソースに出た場合は最初の 1 件のみ追加
            for article in articles:
                if article.url not in seen_urls:
                    seen_urls.add(article.url)
                    all_articles.append(article)
        except Exception as e:
            logger.warning(f"[FETCH] {source['name']}: failed ({e}), skipping")

    return all_articles
```

RSS 取得では `feedparser` の `bozo` フラグを確認します。`bozo=True` かつ `entries` が空の場合はパース失敗として最大 2 回リトライします。

```python
feed = feedparser.parse(source["url"], request_headers={"User-Agent": "NewsBot/1.0"})
if feed.bozo and len(feed.entries) == 0:
    raise ValueError(f"Feed parse error: {feed.bozo_exception}")
```

Hacker News は RSS がないため JSON API を使います。`topstories.json` でトップ ID 一覧を取得し、各記事の詳細を順次リクエストします。「Ask HN」などの URL なし投稿はスキップします。

```python
resp = client.get(f"{base_url}/topstories.json")
top_ids: list[int] = resp.json()[:MAX_ARTICLES_PER_SOURCE]

for item_id in top_ids:
    item = client.get(f"{base_url}/item/{item_id}.json").json()
    if not item.get("url"):
        continue   # Ask HN などはスキップ
```

### 4. Claude へのプロンプト設計

**タイトルと URL だけを渡す**

記事本文は渡しません。タイトルだけでも重要度の判断には十分で、トークンコストを大幅に抑えられます。

**インデックスで記事を参照させる**

Claude に「元の記事リストの何番目か」を `index` として返させます。URL をそのまま返させると転記ミスが起こりやすいですが、インデックスなら間違えようがありません。

```python
# ユーザープロンプトの形式
[0] TechCrunch | OpenAI announces GPT-5
    URL: https://techcrunch.com/...
[1] Zenn | Pythonで始めるLLM開発入門
    URL: https://zenn.dev/...
...（最大 120 件）
```

**JSON のみを出力させる**

前置きや説明文が混入すると後のパースが壊れるため、システムプロンプトで厳しく指定します。

```python
SYSTEM_PROMPT = """あなたはIT・テクノロジー分野の優秀なニュースキュレーターです。
与えられた記事リストから、以下の基準でトップ{n}件を厳選してください。

厳選基準：
- IT・テクノロジーの重要度・インパクト
- 新規性・話題性
- エンジニアやIT従事者への関連性

必ず以下のJSON形式のみで出力してください。説明文や前置きは不要です：
[
  {{
    "index": 記事リストの0始まりインデックス（整数）,
    "rank": 順位（1が最重要）,
    "summary": "1〜2文の日本語要約。元記事が英語でも日本語で書くこと。"
  }}
]"""
```

**レスポンスの堅牢なパース**

「必ず JSON のみ」と指示しても、Claude が稀に前置き文を付けることがあります。`re.search` で JSON 配列部分だけを抽出することで対応しています。

```python
json_match = re.search(r"\[.*\]", response_text, re.DOTALL)
if not json_match:
    raise ValueError(f"Claude response does not contain JSON array: {response_text[:200]}")

ranked_data = json.loads(json_match.group())
```

### 5. Discord への送信

**5 件を 1 リクエストにまとめる**

Discord Webhook は 1 メッセージに最大 10 件の Embed を含められます。5 件をまとめて送ることで API 呼び出しは 1 回で済みます。

**Discord の文字数制限に対応する**

Embed には上限があるため、送信前にクリップします。

| フィールド | Discord の上限 | 本実装での対応 |
|-----------|-------------|-------------|
| title | 256 文字 | `article.title[:256]` |
| description（要約） | 4,096 文字 | `article.summary[:200]`（5件×200文字でも合計1,000文字と余裕あり） |

```python
def _build_payload(articles: list[Article]) -> dict:
    today = datetime.now(JST).strftime("%Y/%m/%d")
    embeds = []
    for article in articles:
        embeds.append({
            "title":       article.title[:256],
            "url":         article.url,
            "description": article.summary[:200],
            "color":       article.color,          # ソースごとに色分け
            "footer":      {"text": article.source},
        })
    return {
        "username": "IT News Bot",
        "content":  f"📰 **本日のITニュース TOP{len(articles)}（{today}）**",
        "embeds":   embeds,
    }
```

**ソースごとにカラーコードを変える**

フッターのソース名と合わせて色でも一目で出所がわかるようにしました。

```python
NEWS_SOURCES = [
    {"name": "Hacker News", "color": 0xFF6600},  # オレンジ
    {"name": "TechCrunch",  "color": 0x33CC44},  # グリーン
    {"name": "The Verge",   "color": 0xFF0000},  # レッド
    {"name": "Zenn",        "color": 0x3CB7D7},  # ブルー
    {"name": "Qiita",       "color": 0x55C500},  # グリーン（濃）
    {"name": "ITmedia",     "color": 0x8B00FF},  # パープル
]
```

**429 / 5xx のみリトライする**

Discord Webhook のエラーをステータスコードで分類し、リトライ対象を絞ります。Webhook URL 自体が誤っている 401 などは即座に失敗させます。

```python
if resp.status_code == 204:
    return  # 成功

if resp.status_code == 429 or resp.status_code >= 500:
    # 5 秒待機してリトライ（最大 3 回）
    raise httpx.HTTPStatusError(...)

resp.raise_for_status()  # 400 / 401 はここで即時例外
```

## ハマったポイント

### 問題①：Lambda Docker イメージのエントリーポイント

Lambda Layer を Docker でビルドする際、最初にこのエラーで詰まりました。

```bash
$ docker run --rm public.ecr.aws/lambda/python:3.13 pip install feedparser ...
entrypoint requires the handler name to be the first argument
```

`public.ecr.aws/lambda/python:3.13` は Lambda 専用の独自エントリーポイントを持っており、渡したコマンドを「Lambda ハンドラー名」として解釈しようとします。`pip` をハンドラー名として渡しても当然失敗します。

`--entrypoint ""` でエントリーポイントを無効化すれば解決します。

```bash
# NG
docker run --rm \
  public.ecr.aws/lambda/python:3.13 \
  pip install -r requirements.txt ...

# OK
docker run --rm \
  --entrypoint "" \                  # ← エントリーポイントを無効化
  public.ecr.aws/lambda/python:3.13 \
  pip install -r requirements.txt ...
```

### 問題②：Apple Silicon Mac でのアーキテクチャ不一致

`--entrypoint ""` を追加してビルドは通ったものの、Lambda にデプロイすると `pydantic-core` や `jiter` など C 拡張ライブラリで動作しない問題が発生しました。

原因は **アーキテクチャの不一致**です。Apple Silicon（ARM64）の Mac では、Docker がデフォルトで ARM64（aarch64）向けにビルドします。一方、Lambda 関数は `x86_64` で作成していたため、バイナリが合いません。

```bash
# 誤ってビルドされた ARM64 バイナリ
$ file layer/python/lib/python3.13/site-packages/pydantic_core/*.so
... ELF 64-bit LSB shared object, ARM aarch64 ...  # ← ARM64！
```

`--platform linux/amd64` を追加して x86_64 向けにビルドし直すことで解決しました。

```bash
# NG：ARM64 バイナリがビルドされる（Apple Silicon Mac のデフォルト）
docker run --rm --entrypoint "" \
  public.ecr.aws/lambda/python:3.13 pip install ...

# OK：--platform linux/amd64 で x86_64 バイナリを強制
docker run --rm --entrypoint "" \
  --platform linux/amd64 \           # ← これが必要
  public.ecr.aws/lambda/python:3.13 pip install ...
```

ビルド後は `file` コマンドで確認することをお勧めします。

```bash
$ file layer/python/lib/python3.13/site-packages/pydantic_core/*.so
... ELF 64-bit LSB shared object, x86-64 ...  # ← x86_64 になった
```

:::message alert
**まとめると Lambda Layer を Apple Silicon Mac でビルドする際は 2 つのオプションが必須です。**
```bash
docker run --rm \
  --entrypoint "" \        # Lambda イメージのエントリーポイントを無効化
  --platform linux/amd64 \ # x86_64 バイナリを強制
  public.ecr.aws/lambda/python:3.13 \
  pip install -r requirements.txt -t /path/to/layer/
```
:::

### 問題③：ローカルテスト時の環境変数

Lambda 本番環境では SSM からシークレットを取得しますが、ローカルで動作確認するたびに `export ANTHROPIC_API_KEY=...` と打つのは面倒ですし、PC の環境変数をシークレットで汚したくありませんでした。

`python-dotenv` と専用の起動スクリプト `run_local.py` で解決しました。`.env` ファイルにシークレットを書き、`.gitignore` に追加します。`load_dotenv()` はそのファイルだけを読み込み、**シェルの環境変数には一切影響しません**。

```python
# run_local.py
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=False)

from lambda_function import lambda_handler
lambda_handler({}, None)
```

```bash
# .env（.gitignore に追加済み）
LOCAL_TEST=1
ANTHROPIC_API_KEY=sk-ant-...
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
DISCORD_CHANNEL_NAME=it-news
```

`ssm_client.py` は `LOCAL_TEST=1` のときだけ環境変数から読み込むよう分岐しています。

```python
def get_config() -> BotConfig:
    if os.environ.get("LOCAL_TEST") == "1":
        # ローカル：環境変数（.env）から読み込む
        return BotConfig(
            anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
            discord_webhook_url=os.environ["DISCORD_WEBHOOK_URL"],
            discord_channel_name=os.environ.get("DISCORD_CHANNEL_NAME", "it-news"),
        )
    # 本番：SSM Parameter Store から取得
    ssm = boto3.client("ssm", region_name=AWS_REGION)
    ...
```

ローカルでの実行は `python run_local.py` だけで完結します。

## デプロイ手順（概要）

デプロイは以下の 7 ステップです。

1. **SSM Parameter Store** にシークレット 3 件を登録
   - `/newsbot/anthropic_api_key`（SecureString）
   - `/newsbot/discord_webhook_url`（SecureString）
   - `/newsbot/discord_channel_name`（String）

2. **Lambda 関数**を作成
   - ランタイム: Python 3.13 / アーキテクチャ: x86_64
   - タイムアウト: 5 分 / メモリ: 256 MB

3. **Lambda の IAM ロール**に SSM 読み取り権限を付与
   ```json
   {
     "Action": ["ssm:GetParameter", "ssm:GetParameters"],
     "Resource": "arn:aws:ssm:ap-northeast-1:*:parameter/newsbot/*"
   }
   ```

4. **Lambda Layer をビルド**（上述の 2 オプション必須）
   ```bash
   docker run --rm --entrypoint "" --platform linux/amd64 \
     public.ecr.aws/lambda/python:3.13 \
     pip install -r requirements.txt -t layer/python/lib/python3.13/site-packages/
   cd layer && zip -r ../newsbot-layer.zip python/
   ```

5. **アプリコードを zip 化**して Lambda にアップロード
   ```bash
   zip newsbot-app.zip lambda_function.py ssm_client.py news_fetcher.py \
       ai_ranker.py discord_notifier.py models.py config.py
   aws lambda update-function-code --function-name newsbot-delivery \
       --zip-file fileb://newsbot-app.zip --region ap-northeast-1
   ```

6. **Layer を Lambda 関数に紐付け**
   ```bash
   aws lambda update-function-configuration \
       --function-name newsbot-delivery \
       --layers arn:aws:lambda:ap-northeast-1:xxxx:layer:newsbot-dependencies:1
   ```

7. **EventBridge Scheduler** でスケジュール設定
   - Cron 式: `cron(0 21 * * ? *)` ＝ UTC 21:00 ＝ JST 翌 06:00

## おわりに

設計・実装・デプロイまで一通り作って気づいたことをまとめます。

**よかった点**
- サーバーレス構成はスケジュール実行ユースケースに非常に相性がよく、EventBridge + Lambda で「毎朝 6 時に何かする」がほぼ設定だけで実現できます
- claude-haiku-4-5 は安価・高速で、大量の記事の中から重要なものを選ぶタスクに十分な精度を発揮しました。英語記事も日本語要約で届くのがかなり便利です
- モジュールを責務ごとに分割したことで、テストが書きやすく、後からソースを追加・変更するときも影響範囲が明確です

**ハマりどころのまとめ**

Apple Silicon Mac で Lambda Layer をビルドする際は、以下の 2 点が罠です。同じ環境の方は最初から付けておくことをお勧めします。

```bash
--entrypoint ""        # Lambda イメージのエントリーポイントを回避
--platform linux/amd64 # x86_64 バイナリを明示的に生成
```

ソースコードは GitHub に公開しています（TODO: リンク）。

---

*動作確認済み環境*

| ライブラリ / サービス | バージョン |
|---------------------|---------|
| Python（Lambda ランタイム） | 3.13 |
| anthropic | 0.79.0 |
| feedparser | 6.0.11 |
| httpx | 0.28.1 |
| Claude モデル | claude-haiku-4-5 |
| AWS Lambda | Python 3.13 ランタイム |
