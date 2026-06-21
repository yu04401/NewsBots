---
title: "毎朝DiscordにAI厳選ITニュースが届くBotをAWS Lambda + Claudeで作った"
emoji: "📰"
type: "tech"
topics: ["aws", "lambda", "python", "discord", "claude"]
published: false
---

## はじめに

毎朝 IT 系ニュースをチェックするのが習慣なのですが、記事が多すぎて重要なものを見逃しがちでした。「重要な記事だけを自動でピックアップして Discord に届けてくれる仕組みがあれば」と思い、作ってみました。

**完成したもの:**
- 6 つのニュースソース（Hacker News / TechCrunch / The Verge / Zenn / Qiita / ITmedia）から最大 120 件の記事を収集
- Claude AI がエンジニア視点でトップ 5 件を厳選・日本語要約
- 毎朝 6:00 に Discord へ自動配信

![Discordに届いたニュース通知のスクリーンショット]()
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

**使用サービス・ライブラリ**

| 用途 | 採用技術 |
|------|---------|
| 実行基盤 | AWS Lambda（Python 3.13） |
| スケジューリング | AWS EventBridge Scheduler |
| シークレット管理 | AWS SSM Parameter Store |
| AI 厳選・要約 | Anthropic Claude claude-haiku-4-5 |
| RSS 取得 | feedparser |
| HTTP クライアント | httpx |
| 配信先 | Discord Webhook |

### AWS 費用について

Lambda・EventBridge・SSM はいずれも今回の使い方では**無料枠内**に収まります。唯一費用がかかるのは Claude API で、1 日 1 回の実行で **月 $0.05〜$0.15 程度**です。

## ディレクトリ構成

```
newsbot/
├── lambda_function.py    # Lambda エントリーポイント
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

各モジュールの責務を明確に分離し、`lambda_function.py` がオーケストレーターとして順番に呼び出す設計にしています。

## 実装のポイント

### 1. Claude へのプロンプト設計

Claude に渡すのはタイトル・URL・ソース名のみで、本文は渡しません。トークンコストを抑えつつ、タイトルだけでも十分に厳選できます。

出力形式を JSON 配列に固定し、「記事の 0 始まりインデックス」で参照させることで URL の転記ミスを防いでいます。

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

```python
# ユーザープロンプト：タイトルと URL のみ渡す
lines = ["以下の記事リストからトップ5件を厳選・要約してください：\n"]
for i, article in enumerate(articles):
    lines.append(f"[{i}] {article.source} | {article.title}")
    lines.append(f"    URL: {article.url}")
```

### 2. データモデルに `slots=True` を使う

`@dataclass(slots=True)` で Article オブジェクトを定義しています。`__slots__` を使うことで通常の dataclass より軽量になり、120 件分のオブジェクトを扱う際のメモリ効率が上がります。

```python
@dataclass(slots=True)
class Article:
    title:   str
    url:     str
    source:  str
    color:   int        # Discord Embed のカラーコード（ソースごとに色分け）
    summary: str = ""   # Claude が後から設定
    rank:    int = 0    # Claude が後から設定
```

### 3. Discord Embed のカラーコードでソースを色分け

1 つの Webhook リクエストに 5 件の Embed をまとめて送信します。ソースごとにカラーコードを変えることで、見た目でどのメディアの記事か一目でわかるようにしています。

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

### 4. 1 ソースが落ちても継続する設計

各ソースの取得は個別に try/except で囲み、失敗しても WARNING ログを出して他のソースの処理を継続します。全ソースが失敗した場合のみ Discord 送信をスキップして Lambda を正常終了させます。

```python
for source in NEWS_SOURCES:
    try:
        articles = _fetch_rss(source)  # 失敗してもここで捕捉
    except Exception as e:
        logger.warning(f"[FETCH] {source['name']}: failed ({e}), skipping")
```

## ハマったポイント

### Lambda イメージのエントリーポイント問題

Lambda Layer を Docker でビルドする際に詰まりました。

`public.ecr.aws/lambda/python:3.13` イメージは Lambda 用の独自エントリーポイントを持っているため、そのまま `pip install` を渡すと「handler 名を指定しろ」というエラーになります。

```bash
# NG: エントリーポイントが pip を handler 名として解釈してしまう
docker run --rm public.ecr.aws/lambda/python:3.13 pip install ...
# → "entrypoint requires the handler name to be the first argument"

# OK: --entrypoint "" でエントリーポイントを無効化する
docker run --rm --entrypoint "" public.ecr.aws/lambda/python:3.13 pip install ...
```

### Apple Silicon Mac でのアーキテクチャ問題

Apple Silicon の Mac では Docker がデフォルトで ARM64（aarch64）向けにビルドします。Lambda の設定を x86_64 にしていたため、そのままでは `pydantic-core` や `jiter` などの C 拡張ライブラリがアーキテクチャ不一致で動きません。

```bash
# NG: ARM64 バイナリがビルドされる（Apple Silicon Mac のデフォルト）
docker run --rm --entrypoint "" public.ecr.aws/lambda/python:3.13 pip install ...

# OK: --platform linux/amd64 で x86_64 バイナリを強制する
docker run --rm --entrypoint "" --platform linux/amd64 \
  public.ecr.aws/lambda/python:3.13 pip install ...
```

ビルド後に以下で確認できます。

```bash
file layer/python/lib/python3.13/site-packages/pydantic_core/*.so
# → ELF 64-bit LSB shared object, x86-64  ← x86_64 であることを確認
```

### ローカルテスト時の環境変数問題

Lambda 環境では SSM からシークレットを取得しますが、ローカルテストのために PC の環境変数をいじりたくありませんでした。

`python-dotenv` と専用の `run_local.py` を用意することで解決しました。`.env` ファイルを `.gitignore` に入れ、`load_dotenv()` でそのファイルだけを読み込む方式です。`export` は一切不要で、PC のシェル環境変数には影響しません。

```python
# run_local.py
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env", override=False)

from lambda_function import lambda_handler
lambda_handler({}, None)
```

```bash
# .env に書いて
LOCAL_TEST=1
ANTHROPIC_API_KEY=sk-ant-...
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# これだけで動く
python run_local.py
```

## デプロイ手順（概要）

1. **SSM Parameter Store** にシークレット 3 件を登録
2. **Lambda 関数**を作成（Python 3.13 / x86_64 / タイムアウト 5 分 / メモリ 256 MB）
3. **Lambda IAM ロール**に SSM 読み取り権限を付与
4. **Lambda Layer をビルド**（Docker で x86_64 向けに pip install → zip）
5. **アプリコードを zip 化**して Lambda にアップロード
6. **Layer を Lambda 関数に紐付け**
7. **EventBridge Scheduler** で `cron(0 21 * * ? *)` を設定（UTC 21:00 = JST 06:00）

## おわりに

設計から実装・デプロイまで一通りやってみて、サーバーレス構成のシンプルさを改めて実感しました。常時起動のサーバーが不要で、コストもほぼゼロ、スケジュール実行も EventBridge に任せるだけです。

Claude claude-haiku-4-5 は安価でレスポンスも速く、今回のような「大量の記事から重要なものを選ぶ」タスクに非常に向いていると感じました。英語記事でも日本語要約で届くのが個人的にかなり便利です。

ソースコードは GitHub に公開しています（TODO: リンク追加）。

---

*本記事で使用した主なバージョン*

| ライブラリ / サービス | バージョン |
|---------------------|---------|
| Python | 3.13 |
| anthropic | 0.79.0 |
| feedparser | 6.0.11 |
| httpx | 0.28.1 |
| AWS Lambda ランタイム | python3.13 |
| Claude モデル | claude-haiku-4-5 |
