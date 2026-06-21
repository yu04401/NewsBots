# Discord ITニュースBot 外部設計書

| 項目 | 内容 |
|------|------|
| バージョン | v1.0 |
| 作成日 | 2026年6月13日 |
| ステータス | 確定 |

---

## 目次

1. [システム概要](#1-システム概要)
2. [システム構成図](#2-システム構成図)
3. [処理フロー](#3-処理フロー)
4. [外部インターフェース設計](#4-外部インターフェース設計)
5. [Discord配信メッセージ設計](#5-discord配信メッセージ設計)
6. [エラー処理設計](#6-エラー処理設計)
7. [ログ設計](#7-ログ設計)
8. [セキュリティ設計](#8-セキュリティ設計)

---

## 1. システム概要

### 1.1 システム目的

毎朝6:00（JST）に複数のIT・テクノロジー系ニュースソースから記事を取得し、Claude AIが重要度・新規性・話題性をもとにトップ5件を厳選・日本語要約してDiscordチャンネルへ自動配信する。

### 1.2 利用者

Discordサーバーの全メンバー（固定配信・カスタマイズなし）

### 1.3 稼働環境

| 項目 | 内容 |
|------|------|
| 実行基盤 | AWS Lambda（Python 3.12） |
| スケジューラ | AWS EventBridge |
| シークレット管理 | AWS SSM Parameter Store |
| ログ | AWS CloudWatch Logs |

---

## 2. システム構成図

```
┌─────────────────────────────────────────────────────────────────┐
│                          AWS Cloud                              │
│                                                                 │
│  ┌─────────────┐    毎朝6:00 JST    ┌───────────────────────┐  │
│  │ EventBridge │ ─────────────────▶ │    Lambda Function    │  │
│  │   (cron)    │                    │    (Python 3.12)      │  │
│  └─────────────┘                    │                       │  │
│                                     │  1. SSMからシークレット取得 │  │
│  ┌─────────────┐                    │  2. RSSフィード取得    │  │
│  │     SSM     │ ◀────────────────▶ │  3. Claude AI厳選・要約 │  │
│  │  Parameter  │                    │  4. Discord Webhook送信 │  │
│  │    Store    │                    │                       │  │
│  └─────────────┘                    └───────────┬───────────┘  │
│                                                 │              │
│  ┌─────────────┐                                │              │
│  │ CloudWatch  │ ◀───────────────────────────────┘              │
│  │    Logs     │  実行ログ                                       │
│  └─────────────┘                                               │
└─────────────────────────────────────────────────────────────────┘
         │                      │                    │
         ▼                      ▼                    ▼
  ┌────────────┐      ┌──────────────────┐   ┌─────────────┐
  │  Hacker    │      │  Anthropic       │   │  Discord    │
  │  News API  │      │  Claude API      │   │  Webhook    │
  │  各種RSS   │      │ (claude-haiku-4-5)│   │  API        │
  └────────────┘      └──────────────────┘   └─────────────┘
```

---

## 3. 処理フロー

### 3.1 全体フロー

```
EventBridgeトリガー（06:00 JST）
        │
        ▼
  ┌───────────┐
  │ SSMから    │  - ANTHROPIC_API_KEY
  │ シークレット │  - DISCORD_WEBHOOK_URL
  │ 取得       │  - DISCORD_CHANNEL_NAME
  └─────┬─────┘
        │
        ▼
  ┌───────────┐
  │ ニュース   │  - 各ソースから並列取得
  │ 取得       │  - 最大20件/ソース
  └─────┬─────┘
        │
        ▼
  ┌───────────┐
  │ Claude AI  │  - 全記事をまとめて送信
  │ 厳選・要約 │  - トップ5件を選出
  └─────┬─────┘
        │
        ▼
  ┌───────────┐
  │ Discord   │  - 指定チャンネルのみに送信
  │ Webhook   │  - Embed形式で5件送信
  │ 送信       │  - 1メッセージに全5件
  └─────┬─────┘
        │
        ▼
  CloudWatch Logs（実行完了ログ）
```

### 3.2 ニュース取得フロー

```
各ソース（並列取得推奨）
    ├── Hacker News API  → JSON取得 → 上位スコア20件
    ├── TechCrunch RSS   → XML取得 → 最新20件
    ├── The Verge RSS    → XML取得 → 最新20件
    ├── Zenn RSS         → XML取得 → 最新20件
    ├── Qiita RSS        → XML取得 → 最新20件
    └── ITmedia RSS      → XML取得 → 最新20件
            │
            ▼
    全記事プール（最大120件）
            │
            ▼
    重複URL排除後、Claude AIへ送信
```

---

## 4. 外部インターフェース設計

### 4.1 ニュースソース

#### 4.1.1 Hacker News API

| 項目 | 内容 |
|------|------|
| プロトコル | HTTPS |
| ベースURL | `https://hacker-news.firebaseio.com/v0/` |
| 認証 | なし（パブリックAPI） |
| 利用エンドポイント | `topstories.json`（上位記事IDリスト）、`item/{id}.json`（記事詳細） |
| 取得件数 | 上位20件 |
| レート制限 | 特になし |

**リクエスト例**
```
GET https://hacker-news.firebaseio.com/v0/topstories.json
GET https://hacker-news.firebaseio.com/v0/item/12345.json
```

**取得フィールド**
```json
{
  "id": 12345,
  "title": "記事タイトル",
  "url": "https://example.com/article",
  "score": 500,
  "time": 1718236800
}
```

---

#### 4.1.2 RSSフィード一覧

| ソース名 | フィードURL | 言語 |
|---------|------------|------|
| TechCrunch | `https://techcrunch.com/feed/` | 英語 |
| The Verge | `https://www.theverge.com/rss/index.xml` | 英語 |
| Zenn トレンド | `https://zenn.dev/feed` | 日本語 |
| Qiita トレンド | `https://qiita.com/popular-items/feed` | 日本語 |
| ITmedia | `https://rss.itmedia.co.jp/rss/2.0/itmediaall.xml` | 日本語 |

**共通取得フィールド（feedparser）**

| フィールド | 内容 |
|-----------|------|
| `entry.title` | 記事タイトル |
| `entry.link` | 記事URL |
| `entry.summary` | 記事概要（存在する場合） |
| `entry.published` | 公開日時 |

---

### 4.2 Anthropic Claude API

| 項目 | 内容 |
|------|------|
| モデル | `claude-haiku-4-5` |
| 認証 | APIキー（SSM Parameter Storeから取得） |
| エンドポイント | Anthropic SDK経由（`anthropic.Anthropic().messages.create()`） |
| タイムアウト | 60秒 |

**リクエスト仕様**

| パラメータ | 値 |
|-----------|---|
| `model` | `claude-haiku-4-5` |
| `max_tokens` | `2048` |
| `temperature` | `0.3`（再現性重視） |

**プロンプト設計**

```
[システムプロンプト]
あなたはIT・テクノロジー分野の優秀なニュースキュレーターです。
与えられた記事リストから、以下の基準でトップ5件を厳選してください。
- IT・テクノロジーの重要度・インパクト
- 新規性・話題性
- エンジニアやIT従事者への関連性

各記事について以下のJSON形式で出力してください：
[
  {
    "rank": 1,
    "title": "記事タイトル（原文）",
    "url": "記事URL",
    "source": "ソース名",
    "summary": "1〜2文の日本語要約"
  },
  ...
]

[ユーザープロンプト]
以下の記事リストからトップ5件を厳選・要約してください：

{記事リスト（タイトル・URL・ソース名）}
```

**レスポンス例**

```json
[
  {
    "rank": 1,
    "title": "OpenAI Releases GPT-5",
    "url": "https://techcrunch.com/...",
    "source": "TechCrunch",
    "summary": "OpenAIが次世代モデルGPT-5を発表。前モデル比で推論精度が大幅に向上し、マルチモーダル機能も強化された。"
  },
  ...
]
```

---

### 4.3 Discord Webhook API

| 項目 | 内容 |
|------|------|
| プロトコル | HTTPS |
| 認証 | Webhook URL（SSM Parameter Storeから取得） |
| 配信チャンネル | SSM `/newsbot/discord_channel_name` で指定した**1チャンネルのみ**に送信。Webhook URL自体がチャンネルに紐付いており、他チャンネルへの誤送信を防ぐ |
| メソッド | POST |
| Content-Type | `application/json` |
| タイムアウト | 30秒 |
| レート制限 | 30リクエスト/秒（Webhookの場合） |

**リクエスト仕様（Embed形式）**

```json
{
  "username": "IT News Bot",
  "avatar_url": null,
  "content": "📰 **本日のITニュース TOP5**（2026/06/13）",
  "embeds": [
    {
      "title": "記事タイトル",
      "url": "https://example.com/article",
      "description": "AIによる日本語要約文（1〜2文）",
      "color": 3447003,
      "footer": {
        "text": "TechCrunch"
      }
    }
  ]
}
```

**Embedカラーコード（ソースごとに色分け）**

| ソース | カラーコード | 色 |
|-------|------------|-----|
| Hacker News | `16737095` | オレンジ |
| TechCrunch | `3394764` | グリーン |
| The Verge | `16711680` | レッド |
| Zenn | `3970327` | ブルー |
| Qiita | `5531650` | グリーン（濃） |
| ITmedia | `9109759` | パープル |
| デフォルト | `3447003` | ブルー |

**レスポンスコード**

| コード | 意味 | 対応 |
|-------|------|------|
| 204 | 送信成功 | 正常終了 |
| 400 | リクエスト不正 | エラーログ出力・処理中断 |
| 401 | Webhook URL無効 | エラーログ出力・処理中断 |
| 429 | レート制限超過 | 5秒待機後リトライ（最大3回） |
| 5xx | Discord側エラー | 5秒待機後リトライ（最大3回） |

---

### 4.4 AWS SSM Parameter Store

| パラメータ名 | 型 | 内容 |
|------------|-----|------|
| `/newsbot/anthropic_api_key` | SecureString | Anthropic APIキー |
| `/newsbot/discord_webhook_url` | SecureString | Discord Webhook URL（配信チャンネルに紐付き） |
| `/newsbot/discord_channel_name` | String | 配信チャンネル名（ログ・確認用。例: `#it-news`） |

**取得方法（Lambda内）**

```python
import boto3
ssm = boto3.client('ssm', region_name='ap-northeast-1')

def get_parameter(name, with_decryption=False):
    response = ssm.get_parameter(Name=name, WithDecryption=with_decryption)
    return response['Parameter']['Value']

api_key      = get_parameter('/newsbot/anthropic_api_key', with_decryption=True)
webhook_url  = get_parameter('/newsbot/discord_webhook_url', with_decryption=True)
channel_name = get_parameter('/newsbot/discord_channel_name')
```

---

## 5. Discord配信メッセージ設計

### 5.1 メッセージ全体構成

1件のWebhookリクエストで5件のEmbedをまとめて送信する。

```
[メッセージ本文]
📰 本日のITニュース TOP5（YYYY/MM/DD）

[Embed 1] ─── 1位記事
[Embed 2] ─── 2位記事
[Embed 3] ─── 3位記事
[Embed 4] ─── 4位記事
[Embed 5] ─── 5位記事
```

### 5.2 Embedフィールド詳細

| フィールド | 内容 | 例 |
|----------|------|-----|
| `title` | 記事タイトル（原文） | `OpenAI Releases GPT-5` |
| `url` | 記事URL | `https://techcrunch.com/...` |
| `description` | AI日本語要約（1〜2文） | `OpenAIが次世代モデルを発表...` |
| `color` | ソース別カラー | `3394764` |
| `footer.text` | ソース名 | `TechCrunch` |

### 5.3 メッセージサンプル

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📰 本日のITニュース TOP5（2026/06/13）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

■ OpenAI Releases GPT-5
  OpenAIが次世代モデルGPT-5を発表。前モデル比で推論精度が大幅に向上し、
  マルチモーダル機能も強化された。
  🔗 https://techcrunch.com/...
  📌 TechCrunch

■ AWSがap-northeast-1リージョンで新サービスを発表
  ...（以下4件続く）
```

---

## 6. エラー処理設計

### 6.1 エラー分類と対応方針

| エラー種別 | 発生箇所 | 対応 | Lambda終了コード |
|----------|---------|------|----------------|
| SSMパラメータ取得失敗 | 起動時 | エラーログ出力・即時終了 | 失敗 |
| 全ニュースソース取得失敗 | ニュース取得 | エラーログ出力・即時終了 | 失敗 |
| 一部ニュースソース取得失敗 | ニュース取得 | 警告ログ出力・他ソースで継続 | 成功 |
| Claude API呼び出し失敗 | AI厳選 | エラーログ出力・即時終了 | 失敗 |
| Claude APIレスポンスパース失敗 | AI厳選 | エラーログ出力・即時終了 | 失敗 |
| Discord Webhook送信失敗（4xx） | Discord送信 | エラーログ出力・即時終了 | 失敗 |
| Discord Webhook送信失敗（5xx/429） | Discord送信 | 5秒待機後リトライ（最大3回） | 失敗（3回失敗時） |

### 6.2 リトライ仕様

| 対象 | 最大リトライ回数 | 待機時間 | 対象エラー |
|-----|--------------|---------|-----------|
| Discord Webhook | 3回 | 5秒（固定） | 429 / 5xx |
| RSS取得 | 2回 | 3秒（固定） | タイムアウト・接続エラー |
| Claude API | リトライなし | - | Anthropic SDK標準に委任 |

### 6.3 取得記事数不足時の挙動

| 取得記事数 | 挙動 |
|----------|------|
| 5件以上 | 正常処理（トップ5件を配信） |
| 1〜4件 | 取得できた件数のみ配信（件数を明示） |
| 0件 | エラーログ出力・Discord送信スキップ・Lambda正常終了 |

---

## 7. ログ設計

### 7.1 ログ出力先

AWS CloudWatch Logs（Lambda自動連携）

- ロググループ: `/aws/lambda/newsbot`
- 保持期間: 30日

### 7.2 ログレベル定義

| レベル | 用途 |
|-------|------|
| INFO | 正常処理の進捗（各フェーズ開始・完了） |
| WARNING | 一部ソース取得失敗など、処理継続可能な異常 |
| ERROR | 処理中断が必要なエラー |

### 7.3 ログ出力仕様

| タイミング | レベル | 内容例 |
|----------|-------|-------|
| Lambda起動 | INFO | `[START] NewsBot Lambda started` |
| SSM取得完了 | INFO | `[SSM] Parameters loaded successfully` |
| ニュース取得開始 | INFO | `[FETCH] Fetching news from 6 sources` |
| 各ソース取得完了 | INFO | `[FETCH] TechCrunch: 20 articles fetched` |
| 一部ソース失敗 | WARNING | `[FETCH] The Verge: failed (timeout), skipping` |
| Claude API送信 | INFO | `[AI] Sending 95 articles to Claude for ranking` |
| Claude API完了 | INFO | `[AI] Top 5 articles selected` |
| Discord送信開始 | INFO | `[DISCORD] Sending message to #it-news (channel_name from SSM)` |
| Discord送信完了 | INFO | `[DISCORD] Message sent successfully to #it-news` |
| Discord送信失敗 | ERROR | `[DISCORD] Failed after 3 retries: 500 Internal Server Error` |
| Lambda正常終了 | INFO | `[END] NewsBot Lambda completed successfully` |
| Lambda異常終了 | ERROR | `[END] NewsBot Lambda failed: {error message}` |

---

## 8. セキュリティ設計

### 8.1 シークレット管理

| シークレット | 保管場所 | 暗号化 | ソースコードへの記載 |
|------------|---------|-------|------------------|
| Anthropic APIキー | SSM Parameter Store（SecureString） | AWS KMS | 禁止 |
| Discord Webhook URL | SSM Parameter Store（SecureString） | AWS KMS | 禁止 |
| 配信チャンネル名 | SSM Parameter Store（String） | なし | 禁止 |

### 8.2 IAM権限設計（Lambdaロール）

Lambda実行ロールに付与する最小権限ポリシー：

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ssm:GetParameter"
      ],
      "Resource": [
        "arn:aws:ssm:ap-northeast-1:*:parameter/newsbot/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:*:*:*"
    }
  ]
}
```

### 8.3 ネットワーク

Lambda関数はVPC外（デフォルト）で実行し、外部APIへのアウトバウンド通信のみ行う。インバウンド通信は存在しない（Webhookは送信のみ）。

---

## 改訂履歴

| バージョン | 日付 | 変更内容 | 作成者 |
|-----------|------|---------|-------|
| v1.0 | 2026/06/13 | 初版作成 | - |
| v1.1 | 2026/06/13 | 配信チャンネル1チャンネル固定化対応（SSMにdiscord_channel_name追加） | - |
