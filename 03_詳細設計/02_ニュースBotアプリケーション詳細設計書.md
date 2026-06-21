# ニュースBot アプリケーション詳細設計書

| 項目 | 内容 |
|------|------|
| バージョン | v1.0 |
| 作成日 | 2026年6月13日 |
| 対象プロジェクト | Discord ITニュースBot |

---

## 目次

1. [ディレクトリ構成](#1-ディレクトリ構成)
2. [依存ライブラリ](#2-依存ライブラリ)
3. [設定値・定数](#3-設定値定数)
4. [データモデル設計](#4-データモデル設計)
5. [モジュール設計](#5-モジュール設計)
6. [各モジュール詳細仕様](#6-各モジュール詳細仕様)
   - 6.1 [lambda_function.py（エントリーポイント）](#61-lambda_functionpyエントリーポイント)
   - 6.2 [ssm_client.py（シークレット取得）](#62-ssm_clientpyシークレット取得)
   - 6.3 [news_fetcher.py（ニュース取得）](#63-news_fetcherpyニュース取得)
   - 6.4 [ai_ranker.py（AI厳選・要約）](#64-ai_rankerpyai厳選要約)
   - 6.5 [discord_notifier.py（Discord送信）](#65-discord_notifierpydiscord送信)
7. [デプロイ構成](#7-デプロイ構成)
8. [ローカルテスト方針](#8-ローカルテスト方針)

---

## 1. ディレクトリ構成

```
newsbot/
├── lambda_function.py       # Lambdaエントリーポイント（ハンドラー）
├── ssm_client.py            # SSM Parameter Storeからシークレット取得
├── news_fetcher.py          # ニュースソースからの記事取得
├── ai_ranker.py             # Claude AIによる厳選・要約
├── discord_notifier.py      # Discord Webhookへの送信
├── models.py                # データモデル（dataclass）
├── config.py                # 定数・設定値
├── requirements.txt         # 依存ライブラリ
└── tests/
    ├── test_news_fetcher.py
    ├── test_ai_ranker.py
    └── test_discord_notifier.py
```

---

## 2. 依存ライブラリ

### requirements.txt

```
feedparser==6.0.11
httpx==0.28.1
anthropic==0.79.0
```

> **標準ライブラリのみで対応するもの（追加インストール不要）**
> - `boto3`: Lambda実行環境に組み込み済み
> - `json`, `logging`, `dataclasses`, `datetime`, `re`: Python標準ライブラリ

### Lambda Layerとしてデプロイする

外部ライブラリ3件はLambda Layerにまとめる。
Lambdaのコードパッケージには `lambda_function.py` 等のアプリコードのみを含める。

**Layerビルド手順（ローカル）**

```bash
# Amazon Linux 2023互換の環境でビルド（Docker利用）
docker run --rm \
  -v $(pwd):/var/task \
  public.ecr.aws/lambda/python:3.13 \
  pip install -r requirements.txt -t /var/task/python/lib/python3.13/site-packages/

# zip化
cd python && zip -r ../newsbot-layer.zip . && cd ..
```

Lambdaコンソール → 「レイヤー」→「レイヤーの作成」から `newsbot-layer.zip` をアップロードし、Lambda関数に紐付ける。

---

## 3. 設定値・定数

### config.py

```python
# ---- SSM パラメータ名 ----
SSM_ANTHROPIC_API_KEY     = "/newsbot/anthropic_api_key"
SSM_DISCORD_WEBHOOK_URL   = "/newsbot/discord_webhook_url"
SSM_DISCORD_CHANNEL_NAME  = "/newsbot/discord_channel_name"

# ---- AWS ----
AWS_REGION = "ap-northeast-1"

# ---- Claude AI ----
CLAUDE_MODEL      = "claude-haiku-4-5"
CLAUDE_MAX_TOKENS = 2048
CLAUDE_TEMPERATURE = 0.3
TOP_N_ARTICLES    = 5          # 配信する記事件数

# ---- ニュース取得 ----
MAX_ARTICLES_PER_SOURCE = 20   # ソースごとの最大取得件数
FETCH_TIMEOUT_SEC       = 10   # RSS取得タイムアウト（秒）
FETCH_MAX_RETRIES       = 2    # RSS取得リトライ回数
FETCH_RETRY_WAIT_SEC    = 3    # リトライ待機時間（秒）

# ---- Discord ----
DISCORD_TIMEOUT_SEC     = 30   # Webhook送信タイムアウト（秒）
DISCORD_MAX_RETRIES     = 3    # Webhook送信リトライ回数
DISCORD_RETRY_WAIT_SEC  = 5    # リトライ待機時間（秒）
DISCORD_BOT_USERNAME    = "IT News Bot"

# ---- ニュースソース ----
NEWS_SOURCES = [
    {
        "name": "Hacker News",
        "type": "hackernews",
        "url": "https://hacker-news.firebaseio.com/v0/topstories.json",
        "color": 0xFF6600,  # オレンジ
    },
    {
        "name": "TechCrunch",
        "type": "rss",
        "url": "https://techcrunch.com/feed/",
        "color": 0x33CC44,  # グリーン
    },
    {
        "name": "The Verge",
        "type": "rss",
        "url": "https://www.theverge.com/rss/index.xml",
        "color": 0xFF0000,  # レッド
    },
    {
        "name": "Zenn",
        "type": "rss",
        "url": "https://zenn.dev/feed",
        "color": 0x3CB7D7,  # ブルー
    },
    {
        "name": "Qiita",
        "type": "rss",
        "url": "https://qiita.com/popular-items/feed",
        "color": 0x55C500,  # グリーン（濃）
    },
    {
        "name": "ITmedia",
        "type": "rss",
        "url": "https://rss.itmedia.co.jp/rss/2.0/news_bursts.xml",
        "color": 0x8B00FF,  # パープル
    },
]
```

---

## 4. データモデル設計

### models.py

```python
from dataclasses import dataclass, field
from typing import Optional


@dataclass(slots=True)
class Article:
    """
    ニュースソースから取得した1件の記事を表すデータモデル。
    """
    title:      str             # 記事タイトル（原文）
    url:        str             # 記事URL
    source:     str             # ソース名（例: "TechCrunch"）
    color:      int             # Discord Embedカラーコード（ソース別）
    summary:    str = ""        # Claude AIが生成した日本語要約（初期値は空）
    rank:       int = 0         # AI厳選後の順位（1〜5）


@dataclass(slots=True)
class BotConfig:
    """
    SSM Parameter Storeから取得したシークレット一式。
    """
    anthropic_api_key:    str
    discord_webhook_url:  str
    discord_channel_name: str
```

---

## 5. モジュール設計

### 役割分担

| モジュール | 責務 | 依存するモジュール |
|-----------|-----|----------------|
| `lambda_function.py` | 処理全体のオーケストレーション | 全モジュール |
| `ssm_client.py` | SSMからシークレットを取得して `BotConfig` を返す | `models.py`, `config.py` |
| `news_fetcher.py` | 各ソースから記事を取得して `list[Article]` を返す | `models.py`, `config.py` |
| `ai_ranker.py` | Claude AIにトップN件を厳選・要約させ `list[Article]` を返す | `models.py`, `config.py` |
| `discord_notifier.py` | `list[Article]` をDiscord Webhookに送信する | `models.py`, `config.py` |

### モジュール間のデータフロー

```
lambda_function.py
    │
    ├─① ssm_client.get_config()
    │       └─ returns: BotConfig
    │
    ├─② news_fetcher.fetch_all_articles()
    │       └─ returns: list[Article]  (重複除去済み)
    │
    ├─③ ai_ranker.rank_and_summarize(articles, config)
    │       └─ returns: list[Article]  (rank・summary が設定済み、TOP5)
    │
    └─④ discord_notifier.send(ranked_articles, config)
            └─ returns: None（成功時）/ raises Exception（失敗時）
```

---

## 6. 各モジュール詳細仕様

### 6.1 lambda_function.py（エントリーポイント）

Lambdaのハンドラー。各モジュールを順番に呼び出し、処理全体を制御する。

**関数シグネチャ**

```python
def lambda_handler(event: dict, context: object) -> dict
```

**処理フロー**

```python
import json
import logging
from ssm_client import get_config
from news_fetcher import fetch_all_articles
from ai_ranker import rank_and_summarize
from discord_notifier import send

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    logger.info("[START] NewsBot Lambda started")

    # ① シークレット取得
    config = get_config()
    logger.info("[SSM] Parameters loaded successfully")

    # ② ニュース取得
    articles = fetch_all_articles()
    logger.info(f"[FETCH] Total {len(articles)} articles collected")

    if len(articles) == 0:
        logger.warning("[FETCH] No articles found. Skipping Discord send.")
        return {"statusCode": 200, "body": "No articles"}

    # ③ AI厳選・要約
    ranked = rank_and_summarize(articles, config)
    logger.info(f"[AI] Top {len(ranked)} articles selected")

    # ④ Discord送信
    send(ranked, config)
    logger.info(f"[DISCORD] Message sent successfully to #{config.discord_channel_name}")

    logger.info("[END] NewsBot Lambda completed successfully")
    return {"statusCode": 200, "body": json.dumps(f"Sent {len(ranked)} articles")}
```

**エラーハンドリング方針**

各モジュールで発生した例外は `lambda_handler` まで伝播させる。Lambda がエラーとして記録し CloudWatch Logs に `[ERROR]` が残る。リトライ処理は各モジュール内で完結させる。

---

### 6.2 ssm_client.py（シークレット取得）

SSM Parameter StoreからAPIキー等を取得して `BotConfig` を返す。

**関数シグネチャ**

```python
def get_config() -> BotConfig
```

**実装**

```python
import boto3
import logging
from models import BotConfig
from config import (
    AWS_REGION,
    SSM_ANTHROPIC_API_KEY,
    SSM_DISCORD_WEBHOOK_URL,
    SSM_DISCORD_CHANNEL_NAME,
)

logger = logging.getLogger(__name__)

def get_config() -> BotConfig:
    """
    SSM Parameter Storeから全シークレットを取得して BotConfig を返す。

    Raises:
        Exception: パラメータ取得に失敗した場合
    """
    ssm = boto3.client("ssm", region_name=AWS_REGION)

    def _get(name: str, decrypt: bool = False) -> str:
        response = ssm.get_parameter(Name=name, WithDecryption=decrypt)
        return response["Parameter"]["Value"]

    api_key      = _get(SSM_ANTHROPIC_API_KEY,    decrypt=True)
    webhook_url  = _get(SSM_DISCORD_WEBHOOK_URL,  decrypt=True)
    channel_name = _get(SSM_DISCORD_CHANNEL_NAME, decrypt=False)

    return BotConfig(
        anthropic_api_key=api_key,
        discord_webhook_url=webhook_url,
        discord_channel_name=channel_name,
    )
```

**エラーハンドリング**

| 例外 | 原因 | 対処 |
|-----|------|------|
| `ssm.exceptions.ParameterNotFound` | パラメータ名の誤り | 例外をそのまま上位へ伝播。Lambdaが失敗として記録 |
| `ClientError (AccessDeniedException)` | IAMロールのSSM権限不足 | 同上 |

---

### 6.3 news_fetcher.py（ニュース取得）

各ニュースソースから記事を取得し、重複を除去した `list[Article]` を返す。

**関数シグネチャ**

```python
def fetch_all_articles() -> list[Article]
def _fetch_rss(source: dict) -> list[Article]
def _fetch_hackernews(source: dict) -> list[Article]
```

**実装**

```python
import time
import logging
import feedparser
import httpx
from models import Article
from config import (
    NEWS_SOURCES,
    MAX_ARTICLES_PER_SOURCE,
    FETCH_TIMEOUT_SEC,
    FETCH_MAX_RETRIES,
    FETCH_RETRY_WAIT_SEC,
)

logger = logging.getLogger(__name__)


def fetch_all_articles() -> list[Article]:
    """
    全ソースから記事を取得し、URL重複を除去して返す。
    一部ソースの失敗は警告ログに記録して処理を継続する。
    """
    all_articles: list[Article] = []
    seen_urls: set[str] = set()

    for source in NEWS_SOURCES:
        try:
            if source["type"] == "hackernews":
                articles = _fetch_hackernews(source)
            else:
                articles = _fetch_rss(source)

            logger.info(f"[FETCH] {source['name']}: {len(articles)} articles fetched")

            for article in articles:
                if article.url not in seen_urls:
                    seen_urls.add(article.url)
                    all_articles.append(article)

        except Exception as e:
            logger.warning(f"[FETCH] {source['name']}: failed ({e}), skipping")

    return all_articles


def _fetch_rss(source: dict) -> list[Article]:
    """
    RSS/AtomフィードをfeedparserでパースしてArticleリストを返す。
    最大 MAX_ARTICLES_PER_SOURCE 件を返す。
    """
    for attempt in range(FETCH_MAX_RETRIES + 1):
        try:
            feed = feedparser.parse(
                source["url"],
                request_headers={"User-Agent": "NewsBot/1.0"},
            )

            # feedparserはネットワーク失敗時にbozo=1を立てる
            if feed.bozo and len(feed.entries) == 0:
                raise ValueError(f"Feed parse error: {feed.bozo_exception}")

            articles = []
            for entry in feed.entries[:MAX_ARTICLES_PER_SOURCE]:
                url   = getattr(entry, "link", "")
                title = getattr(entry, "title", "")
                if not url or not title:
                    continue
                articles.append(Article(
                    title=title.strip(),
                    url=url.strip(),
                    source=source["name"],
                    color=source["color"],
                ))
            return articles

        except Exception as e:
            if attempt < FETCH_MAX_RETRIES:
                logger.warning(f"[FETCH] {source['name']}: retry {attempt + 1} ({e})")
                time.sleep(FETCH_RETRY_WAIT_SEC)
            else:
                raise


def _fetch_hackernews(source: dict) -> list[Article]:
    """
    Hacker News APIからトップ記事を取得してArticleリストを返す。
    トップ記事IDを取得 → 上位 MAX_ARTICLES_PER_SOURCE 件の詳細を取得する。
    """
    base_url = "https://hacker-news.firebaseio.com/v0"

    with httpx.Client(timeout=FETCH_TIMEOUT_SEC) as client:
        # トップ記事IDリストを取得
        resp = client.get(f"{base_url}/topstories.json")
        resp.raise_for_status()
        top_ids: list[int] = resp.json()[:MAX_ARTICLES_PER_SOURCE]

        articles = []
        for item_id in top_ids:
            try:
                resp = client.get(f"{base_url}/item/{item_id}.json")
                resp.raise_for_status()
                item = resp.json()

                url   = item.get("url", "")
                title = item.get("title", "")
                if not url or not title:
                    continue  # Ask HNなどURLなし記事はスキップ

                articles.append(Article(
                    title=title.strip(),
                    url=url.strip(),
                    source=source["name"],
                    color=source["color"],
                ))
            except Exception:
                continue  # 個別記事の失敗はスキップして継続

    return articles
```

**エラーハンドリング**

| 状況 | 挙動 |
|-----|------|
| RSSパースエラー（bozo=1） | リトライ後も失敗なら WARNING ログ → そのソースをスキップ |
| タイムアウト | `FETCH_MAX_RETRIES` 回リトライ → 失敗なら WARNING → スキップ |
| HN個別記事取得失敗 | その記事をスキップ（他の記事は継続取得） |
| 全ソース失敗 | `fetch_all_articles()` が空リストを返す → `lambda_handler` が送信をスキップ |

---

### 6.4 ai_ranker.py（AI厳選・要約）

Claude AIに記事リストを渡し、トップ `TOP_N_ARTICLES` 件を厳選・日本語要約させる。

**関数シグネチャ**

```python
def rank_and_summarize(articles: list[Article], config: BotConfig) -> list[Article]
def _build_prompt(articles: list[Article]) -> str
def _parse_response(response_text: str, articles: list[Article]) -> list[Article]
```

**実装**

```python
import json
import logging
import re
from anthropic import Anthropic
from models import Article, BotConfig
from config import (
    CLAUDE_MODEL,
    CLAUDE_MAX_TOKENS,
    CLAUDE_TEMPERATURE,
    TOP_N_ARTICLES,
)

logger = logging.getLogger(__name__)

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

def rank_and_summarize(articles: list[Article], config: BotConfig) -> list[Article]:
    """
    Claude AIで記事を厳選・要約する。

    Args:
        articles: 重複除去済みの全記事リスト
        config:   APIキーを含む設定

    Returns:
        rankとsummaryが設定されたArticleリスト（TOP_N_ARTICLES件以下）

    Raises:
        Exception: Claude API呼び出し失敗、またはレスポンスパース失敗
    """
    client = Anthropic(api_key=config.anthropic_api_key)

    user_prompt = _build_prompt(articles)
    system = SYSTEM_PROMPT.format(n=TOP_N_ARTICLES)

    logger.info(f"[AI] Sending {len(articles)} articles to Claude for ranking")

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=CLAUDE_MAX_TOKENS,
        temperature=CLAUDE_TEMPERATURE,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
    )

    response_text = response.content[0].text
    ranked = _parse_response(response_text, articles)

    return ranked


def _build_prompt(articles: list[Article]) -> str:
    """
    記事リストをClaudeに渡すプロンプト文字列に変換する。

    出力例:
        以下の記事リストからトップ5件を厳選・要約してください：

        [0] TechCrunch | OpenAI Releases GPT-5
            URL: https://techcrunch.com/...
        [1] Zenn | Pythonで始めるLLM開発
            URL: https://zenn.dev/...
    """
    lines = ["以下の記事リストからトップ5件を厳選・要約してください：\n"]
    for i, article in enumerate(articles):
        lines.append(f"[{i}] {article.source} | {article.title}")
        lines.append(f"    URL: {article.url}")
    return "\n".join(lines)


def _parse_response(response_text: str, articles: list[Article]) -> list[Article]:
    """
    ClaudeのレスポンスJSONをパースし、元のArticleオブジェクトに
    rank と summary を設定して返す。

    Raises:
        ValueError: JSONパース失敗またはindexが範囲外の場合
    """
    # Claudeが余分な文字を含む場合に備えてJSON配列部分を抽出
    json_match = re.search(r"\[.*\]", response_text, re.DOTALL)
    if not json_match:
        raise ValueError(f"Claude response does not contain JSON array: {response_text[:200]}")

    ranked_data: list[dict] = json.loads(json_match.group())

    result: list[Article] = []
    for item in sorted(ranked_data, key=lambda x: x["rank"]):
        idx = item["index"]
        if not (0 <= idx < len(articles)):
            raise ValueError(f"Article index {idx} out of range (total: {len(articles)})")

        article = articles[idx]
        article.rank = item["rank"]
        article.summary = item["summary"]
        result.append(article)

    return result
```

**エラーハンドリング**

| 状況 | 挙動 |
|-----|------|
| Claude API接続失敗 | 例外を上位へ伝播 → Lambda失敗として記録 |
| レスポンスにJSON配列がない | `ValueError` を raise → Lambda失敗 |
| indexが範囲外 | `ValueError` を raise → Lambda失敗 |

**プロンプト設計詳細**

| 項目 | 値 |
|-----|---|
| `model` | `claude-haiku-4-5` |
| `max_tokens` | `2048` |
| `temperature` | `0.3`（再現性重視・ランダム性を抑える） |
| 出力形式 | JSON配列（index・rank・summary） |
| index方式 | 0始まりの整数インデックスで記事を特定（URL変換コスト削減） |

---

### 6.5 discord_notifier.py（Discord送信）

厳選記事リストをDiscord Webhook APIに送信する。

**関数シグネチャ**

```python
def send(articles: list[Article], config: BotConfig) -> None
def _build_payload(articles: list[Article]) -> dict
```

**実装**

```python
import time
import logging
import httpx
from datetime import datetime, timezone, timedelta
from models import Article, BotConfig
from config import (
    DISCORD_TIMEOUT_SEC,
    DISCORD_MAX_RETRIES,
    DISCORD_RETRY_WAIT_SEC,
    DISCORD_BOT_USERNAME,
    TOP_N_ARTICLES,
)

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))


def send(articles: list[Article], config: BotConfig) -> None:
    """
    記事リストをEmbed形式でDiscord Webhookに送信する。
    429/5xxエラーは DISCORD_MAX_RETRIES 回リトライする。

    Args:
        articles: rank・summaryが設定済みのArticleリスト
        config:   Webhook URLとチャンネル名を含む設定

    Raises:
        Exception: リトライ上限を超えて失敗した場合
    """
    payload = _build_payload(articles)
    logger.info(f"[DISCORD] Sending message to #{config.discord_channel_name}")

    for attempt in range(DISCORD_MAX_RETRIES + 1):
        try:
            with httpx.Client(timeout=DISCORD_TIMEOUT_SEC) as client:
                resp = client.post(config.discord_webhook_url, json=payload)

            if resp.status_code == 204:
                return  # 送信成功

            if resp.status_code == 429 or resp.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"HTTP {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )

            # 400/401 などリトライ不要なエラー
            resp.raise_for_status()

        except httpx.HTTPStatusError as e:
            if attempt < DISCORD_MAX_RETRIES:
                logger.warning(
                    f"[DISCORD] Retry {attempt + 1}/{DISCORD_MAX_RETRIES} ({e})"
                )
                time.sleep(DISCORD_RETRY_WAIT_SEC)
            else:
                raise Exception(
                    f"[DISCORD] Failed after {DISCORD_MAX_RETRIES} retries: {e}"
                ) from e


def _build_payload(articles: list[Article]) -> dict:
    """
    ArticleリストからDiscord Webhook用のペイロードdictを生成する。

    Discord制約:
        - 1メッセージあたり最大10 Embed（今回は最大5件なので問題なし）
        - 全Embed合計6,000文字以内
    """
    today = datetime.now(JST).strftime("%Y/%m/%d")
    count = len(articles)
    header = f"本日のITニュース TOP{count}（{today}）"

    embeds = []
    for article in articles:
        # description の文字数を制限（全embed合計6000文字を守るため）
        summary = article.summary[:200] if len(article.summary) > 200 else article.summary

        embeds.append({
            "title":       article.title[:256],   # Discord上限: 256文字
            "url":         article.url,
            "description": summary,
            "color":       article.color,
            "footer":      {"text": article.source},
        })

    return {
        "username": DISCORD_BOT_USERNAME,
        "content":  f"📰 **{header}**",
        "embeds":   embeds,
    }
```

**エラーハンドリング**

| HTTPステータス | 挙動 |
|-------------|-----|
| 204 | 正常終了 |
| 429 | `DISCORD_RETRY_WAIT_SEC` 秒待機後リトライ（最大 `DISCORD_MAX_RETRIES` 回） |
| 5xx | 同上 |
| 400 | リトライなし。`raise_for_status()` で例外 → Lambda失敗 |
| 401 | 同上（Webhook URL無効） |

**Discord制約チェック**

| 制約 | 上限 | 本実装での対応 |
|-----|-----|-------------|
| 1メッセージあたりEmbed数 | 10件 | 最大5件のため問題なし |
| 全Embed合計文字数 | 6,000文字 | summary を200文字以内に切り詰め（5件×200文字=1,000文字で余裕あり） |
| Embed title | 256文字 | `title[:256]` でクリップ |
| Embed description | 4,096文字 | summary の200文字制限により問題なし |

---

## 7. デプロイ構成

### 7.1 パッケージ構成

```
デプロイ成果物
├── newsbot-app.zip          # アプリコード（Lambda関数本体）
│   ├── lambda_function.py
│   ├── ssm_client.py
│   ├── news_fetcher.py
│   ├── ai_ranker.py
│   ├── discord_notifier.py
│   ├── models.py
│   └── config.py
│
└── newsbot-layer.zip        # Lambda Layer（外部ライブラリ）
    └── python/
        └── lib/
            └── python3.13/
                └── site-packages/
                    ├── feedparser/
                    ├── httpx/
                    └── anthropic/
```

### 7.2 ビルド・デプロイ手順

```bash
# ① Layer のビルド（要Docker）
docker run --rm \
  -v $(pwd):/var/task \
  public.ecr.aws/lambda/python:3.13 \
  pip install -r requirements.txt -t /var/task/layer/python/lib/python3.13/site-packages/

cd layer && zip -r ../newsbot-layer.zip python/ && cd ..

# ② アプリコードのzip化
zip newsbot-app.zip \
  lambda_function.py ssm_client.py news_fetcher.py \
  ai_ranker.py discord_notifier.py models.py config.py

# ③ Layer のアップロード（AWS CLI）
aws lambda publish-layer-version \
  --layer-name newsbot-dependencies \
  --zip-file fileb://newsbot-layer.zip \
  --compatible-runtimes python3.13 \
  --region ap-northeast-1

# ④ アプリコードのアップロード
aws lambda update-function-code \
  --function-name newsbot-delivery \
  --zip-file fileb://newsbot-app.zip \
  --region ap-northeast-1

# ⑤ LayerをLambda関数に紐付け（LayerのARNは③の出力を参照）
aws lambda update-function-configuration \
  --function-name newsbot-delivery \
  --layers arn:aws:lambda:ap-northeast-1:123456789012:layer:newsbot-dependencies:1 \
  --region ap-northeast-1
```

---

## 8. ローカルテスト方針

### 8.1 環境変数の設定（ローカル実行時）

```bash
export ANTHROPIC_API_KEY="your-api-key"
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
export DISCORD_CHANNEL_NAME="it-news"
```

ローカル実行時はSSMの代わりに環境変数から読み込むよう `ssm_client.py` に分岐を加えるとテストが容易になる。

### 8.2 各モジュールの単体テスト観点

| モジュール | テスト観点 |
|-----------|---------|
| `news_fetcher.py` | RSSパース成功・bozo=1時のリトライ・空フィード時の挙動 |
| `ai_ranker.py` | Claudeレスポンスのパース成功・JSON不正時のValueError・indexが範囲外のエラー |
| `discord_notifier.py` | payload生成の文字数制限・204/429/400時の挙動・リトライ回数の正確性 |

### 8.3 Lambda手動テストペイロード

```json
{}
```

Lambda コンソールの「テスト」タブでイベントを `{}` として実行する。処理結果は CloudWatch Logs で確認する。

---

## 改訂履歴

| バージョン | 日付 | 変更内容 | 作成者 |
|-----------|------|---------|-------|
| v1.0 | 2026/06/13 | 初版作成 | - |
