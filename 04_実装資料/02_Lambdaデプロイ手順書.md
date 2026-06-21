# Lambda デプロイ手順書

| 項目 | 内容 |
|------|------|
| バージョン | v1.0 |
| 作成日 | 2026年6月21日 |
| 前提ドキュメント | `03_詳細設計/01_AWSセットアップ手順書.md` |

---

## 目次

1. [全体の流れ](#1-全体の流れ)
2. [前提条件の確認](#2-前提条件の確認)
3. [AWS CLI のセットアップ](#3-aws-cli-のセットアップ)
4. [SSM Parameter Store への登録](#4-ssm-parameter-store-への登録)
5. [Lambda 関数・IAM ロールの作成](#5-lambda-関数iamロールの作成)
6. [Lambda Layer のビルドとアップロード](#6-lambda-layer-のビルドとアップロード)
7. [アプリコードのアップロード](#7-アプリコードのアップロード)
8. [Lambda の設定確認](#8-lambda-の設定確認)
9. [動作確認](#9-動作確認)
10. [EventBridge スケジュールの有効化](#10-eventbridge-スケジュールの有効化)

---

## 1. 全体の流れ

```
STEP 1  前提条件の確認
        └─ Docker・AWS CLI・AWS アカウント

STEP 2  AWS CLI の認証設定
        └─ IAM Identity Center（SSO）でログイン

STEP 3  SSM Parameter Store にシークレットを登録
        ├─ /newsbot/anthropic_api_key   (SecureString)
        ├─ /newsbot/discord_webhook_url (SecureString)
        └─ /newsbot/discord_channel_name (String)

STEP 4  Lambda 関数・IAM ロールを作成（コンソール）
        └─ SSM 読み取り権限のインラインポリシーを付与

STEP 5  Lambda Layer をビルド（Docker）
        └─ feedparser / httpx / anthropic を Python 3.13 向けにビルド

STEP 6  Layer と アプリコードを Lambda にアップロード
        └─ AWS CLI で zip をアップロード

STEP 7  Lambda の設定を確認
        └─ ハンドラー名 / タイムアウト / メモリ / Layer 紐付け

STEP 8  Lambda コンソールから手動テスト実行
        └─ CloudWatch Logs と Discord で結果を確認

STEP 9  EventBridge スケジュールを有効化
        └─ 毎朝 6:00 JST の自動実行を確認
```

---

## 2. 前提条件の確認

### 必要なもの

| 項目 | 確認方法 |
|------|---------|
| Docker Desktop（起動済み） | `docker --version` でバージョンが表示される |
| AWS アカウント（作成済み） | `03_詳細設計/01_AWSセットアップ手順書.md` STEP 1〜4 が完了済み |
| AWS CLI v2 | 次のセクションでインストール |
| Anthropic API キー | [console.anthropic.com](https://console.anthropic.com) で取得済み |
| Discord Webhook URL | Discord チャンネル設定から取得済み |

### Docker の起動確認

```bash
docker --version
# 出力例: Docker version 27.x.x, build xxxxxxx
```

Docker が起動していない場合は Docker Desktop を起動してから進む。

---

## 3. AWS CLI のセットアップ

### 3.1 AWS CLI v2 のインストール

```bash
# macOS（Apple Silicon / Intel 共通）
curl "https://awscli.amazonaws.com/AWSCLIV2.pkg" -o "AWSCLIV2.pkg"
sudo installer -pkg AWSCLIV2.pkg -target /
aws --version
# 出力例: aws-cli/2.x.x Python/3.x.x Darwin/...
```

### 3.2 IAM Identity Center（SSO）との連携設定

> IAM Identity Center のセットアップが完了していない場合は先に
> `03_詳細設計/01_AWSセットアップ手順書.md` の STEP 4〜5 を実施すること。

```bash
aws configure sso
```

対話形式で以下を入力する。

| プロンプト | 入力値 |
|-----------|-------|
| SSO session name | `newsbot` |
| SSO start URL | `https://d-xxxxxxxxxx.awsapps.com/start`（Identity Center の URL） |
| SSO region | `ap-northeast-1` |
| SSO registration scopes | Enter（デフォルトのまま） |

ブラウザが開き AWS へのアクセス許可を求められるので「Allow」をクリック。
ターミナルに戻り、以下を選択・入力する。

| プロンプト | 入力値 |
|-----------|-------|
| CLI default client Region | `ap-northeast-1` |
| CLI default output format | `json` |
| CLI profile name | `newsbot` |

### 3.3 ログイン確認

```bash
aws sso login --profile newsbot
aws sts get-caller-identity --profile newsbot
```

**期待する出力:**

```json
{
    "UserId": "XXXXXXXXXXXXXXXXX:admin",
    "Account": "123456789012",
    "Arn": "arn:aws:sts::123456789012:assumed-role/..."
}
```

以降のコマンドはすべて `--profile newsbot` を付けて実行する。

---

## 4. SSM Parameter Store への登録

> すでに登録済みの場合はこのセクションをスキップ。

### 4.1 登録コマンド

以下の 3 コマンドを実行する（値は自分のものに置き換える）。

```bash
# ① Anthropic API キー（SecureString）
aws ssm put-parameter \
  --name "/newsbot/anthropic_api_key" \
  --type "SecureString" \
  --value "sk-ant-xxxxxxxxxx" \
  --description "Anthropic Claude API キー" \
  --region ap-northeast-1 \
  --profile newsbot

# ② Discord Webhook URL（SecureString）
aws ssm put-parameter \
  --name "/newsbot/discord_webhook_url" \
  --type "SecureString" \
  --value "https://discord.com/api/webhooks/xxxxxxxxxx/xxxxxxxxxx" \
  --description "Discord Webhook URL（配信チャンネルに紐付き）" \
  --region ap-northeast-1 \
  --profile newsbot

# ③ Discord チャンネル名（String）
aws ssm put-parameter \
  --name "/newsbot/discord_channel_name" \
  --type "String" \
  --value "it-news" \
  --description "配信先 Discord チャンネル名（ログ確認用）" \
  --region ap-northeast-1 \
  --profile newsbot
```

### 4.2 登録確認

```bash
aws ssm get-parameters-by-path \
  --path "/newsbot/" \
  --with-decryption \
  --region ap-northeast-1 \
  --profile newsbot \
  --query "Parameters[].{Name:Name,Type:Type}" \
  --output table
```

**期待する出力:**

```
-----------------------------------------
|         GetParametersByPath           |
+----------------------------+----------+
|           Name             |   Type   |
+----------------------------+----------+
|  /newsbot/anthropic_api_key|SecureString|
|  /newsbot/discord_channel_name|String |
|  /newsbot/discord_webhook_url|SecureString|
+----------------------------+----------+
```

---

## 5. Lambda 関数・IAM ロールの作成

> すでに作成済みの場合はこのセクションをスキップ。
> 詳細手順は `03_詳細設計/01_AWSセットアップ手順書.md` STEP 7〜8 を参照。

### 5.1 Lambda 関数の作成（コンソール）

1. AWS コンソール → Lambda → **「関数の作成」**
2. 以下の設定で作成:

| 設定項目 | 値 |
|---------|---|
| 作成方法 | 一から作成 |
| 関数名 | `newsbot-delivery` |
| ランタイム | **Python 3.13** |
| アーキテクチャ | **x86_64** |
| 実行ロール | 基本的な Lambda アクセス権限で新しいロールを作成 |

### 5.2 タイムアウト・メモリの変更

「設定」タブ → 「一般設定」→「編集」

| 項目 | 変更後の値 |
|------|---------|
| タイムアウト | 5 分（300 秒） |
| メモリ | 256 MB |

### 5.3 IAM ロールに SSM 権限を付与

1. 「設定」タブ → 「アクセス権限」→ ロール名のリンクをクリック（IAM コンソールへ）
2. 「許可を追加」→「インラインポリシーを作成」→「JSON」タブに以下を貼り付け

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "SSMReadNewsbot",
      "Effect": "Allow",
      "Action": [
        "ssm:GetParameter",
        "ssm:GetParameters"
      ],
      "Resource": "arn:aws:ssm:ap-northeast-1:*:parameter/newsbot/*"
    }
  ]
}
```

3. ポリシー名: `NewsBot-SSMReadPolicy` → 「ポリシーを作成」

---

## 6. Lambda Layer のビルドとアップロード

Lambda の実行環境は **Amazon Linux 2023 / x86_64** のため、Docker を使って同環境でライブラリをビルドする。

### 6.1 ビルド

```bash
cd NewsBot/newsbot

# layer ディレクトリを準備（既存があれば削除してリセット）
rm -rf layer newsbot-layer.zip
mkdir -p layer

# Python 3.13 / x86_64 向けに Amazon Linux 互換環境でビルド
# --platform linux/amd64 : Apple Silicon Mac でも x86_64 バイナリを生成する（必須）
# --entrypoint ""         : Lambda イメージのエントリーポイントを無効化して pip を直接実行する（必須）
docker run --rm \
  --platform linux/amd64 \
  --entrypoint "" \
  -v "$(pwd)":/var/task \
  public.ecr.aws/lambda/python:3.13 \
  pip install -r /var/task/requirements.txt \
      -t /var/task/layer/python/lib/python3.13/site-packages/ \
      --no-cache-dir

echo "Build complete. Contents:"
ls layer/python/lib/python3.13/site-packages/ | head -10
```

**期待する出力（例）:**

```
Build complete. Contents:
anthropic
anthropic-0.79.0.dist-info
certifi
feedparser
httpx
...
```

### 6.2 zip 化

```bash
cd layer
zip -r ../newsbot-layer.zip python/
cd ..
ls -lh newsbot-layer.zip
# 出力例: -rw-r--r-- 1 user staff  12M Jun 21 10:00 newsbot-layer.zip
```

### 6.3 Layer を Lambda にアップロード

```bash
LAYER_ARN=$(aws lambda publish-layer-version \
  --layer-name newsbot-dependencies \
  --description "feedparser / httpx / anthropic for Python 3.13" \
  --zip-file fileb://newsbot-layer.zip \
  --compatible-runtimes python3.13 \
  --compatible-architectures x86_64 \
  --region ap-northeast-1 \
  --profile newsbot \
  --query "LayerVersionArn" \
  --output text)

echo "Layer ARN: ${LAYER_ARN}"
```

**期待する出力:**

```
Layer ARN: arn:aws:lambda:ap-northeast-1:123456789012:layer:newsbot-dependencies:1
```

この ARN を次のセクションで使うためメモしておく。

---

## 7. アプリコードのアップロード

### 7.1 アプリコードの zip 化

```bash
cd NewsBot/newsbot

zip newsbot-app.zip \
  lambda_function.py \
  ssm_client.py \
  news_fetcher.py \
  ai_ranker.py \
  discord_notifier.py \
  models.py \
  config.py

ls -lh newsbot-app.zip
# 出力例: -rw-r--r-- 1 user staff  12K Jun 21 10:05 newsbot-app.zip
```

### 7.2 Lambda 関数にアップロード

```bash
aws lambda update-function-code \
  --function-name newsbot-delivery \
  --zip-file fileb://newsbot-app.zip \
  --region ap-northeast-1 \
  --profile newsbot
```

**期待する出力（抜粋）:**

```json
{
    "FunctionName": "newsbot-delivery",
    "Runtime": "python3.13",
    "Handler": "lambda_function.lambda_handler",
    ...
}
```

### 7.3 Layer を Lambda 関数に紐付け

`${LAYER_ARN}` は [6.3](#63-layer-を-lambda-にアップロード) で確認した ARN に置き換える。

```bash
aws lambda update-function-configuration \
  --function-name newsbot-delivery \
  --layers "${LAYER_ARN}" \
  --region ap-northeast-1 \
  --profile newsbot \
  --query "{Handler:Handler, Runtime:Runtime, Layers:Layers}"
```

**期待する出力:**

```json
{
    "Handler": "lambda_function.lambda_handler",
    "Runtime": "python3.13",
    "Layers": [
        {
            "Arn": "arn:aws:lambda:ap-northeast-1:123456789012:layer:newsbot-dependencies:1",
            ...
        }
    ]
}
```

---

## 8. Lambda の設定確認

デプロイ後に以下をコンソールまたは CLI で確認する。

### 8.1 確認項目チェックリスト

```bash
aws lambda get-function-configuration \
  --function-name newsbot-delivery \
  --region ap-northeast-1 \
  --profile newsbot \
  --query "{Handler:Handler, Runtime:Runtime, Timeout:Timeout, MemorySize:MemorySize, Layers:Layers[*].Arn}"
```

**期待する出力:**

```json
{
    "Handler": "lambda_function.lambda_handler",
    "Runtime": "python3.13",
    "Timeout": 300,
    "MemorySize": 256,
    "Layers": [
        "arn:aws:lambda:ap-northeast-1:123456789012:layer:newsbot-dependencies:1"
    ]
}
```

| 確認項目 | 正しい値 | NG の場合の対処 |
|---------|---------|--------------|
| Handler | `lambda_function.lambda_handler` | Lambda コンソール「コード」→「ランタイム設定」で修正 |
| Runtime | `python3.13` | Lambda コンソール「コード」→「ランタイム設定」で修正 |
| Timeout | `300`（5 分） | [5.2](#52-タイムアウトメモリの変更) を再実施 |
| MemorySize | `256` | [5.2](#52-タイムアウトメモリの変更) を再実施 |
| Layers | ARN が 1 件ある | [7.3](#73-layer-を-lambda-関数に紐付け) を再実施 |

---

## 9. 動作確認

### 9.1 Lambda コンソールから手動テスト

1. Lambda コンソール → `newsbot-delivery` → **「テスト」タブ**
2. 「テストイベントを作成」→ 以下を設定して「保存」:

| 設定項目 | 値 |
|---------|---|
| イベント名 | `manual-test` |
| イベント JSON | `{}` |

3. **「テスト」** ボタンをクリック
4. 実行完了まで待つ（最大 5 分）

### 9.2 実行結果の確認

**成功パターン:**

```json
{
  "statusCode": 200,
  "body": "\"Sent 5 articles\""
}
```

### 9.3 CloudWatch Logs の確認

「モニタリング」タブ → **「CloudWatch のログを表示」** → 最新のログストリームを開く。

正常終了時は以下の順序でログが出力されている。

```
[START] NewsBot Lambda started
[SSM] Parameters loaded successfully
[FETCH] Fetching news from 6 sources
[FETCH] Hacker News: XX articles fetched
[FETCH] TechCrunch: XX articles fetched
[FETCH] The Verge: XX articles fetched
[FETCH] Zenn: XX articles fetched
[FETCH] Qiita: XX articles fetched
[FETCH] ITmedia: XX articles fetched
[FETCH] Total XX articles collected
[AI] Sending XX articles to Claude for ranking
[AI] Top 5 articles selected
[DISCORD] Sending message to #it-news
[DISCORD] Message sent successfully to #it-news
[END] NewsBot Lambda completed successfully
```

### 9.4 Discord での確認

指定したチャンネルに 5 件の Embed メッセージが投稿されていることを確認する。

### 9.5 初回エラー対処表

| エラーメッセージ | 原因 | 対処 |
|---------------|-----|------|
| `AccessDeniedException: ssm:GetParameter` | Lambda IAM ロールの SSM 権限不足 | [5.3](#53-iam-ロールに-ssm-権限を付与) を再確認 |
| `ParameterNotFound: /newsbot/...` | SSM パラメータ名が不一致 | [4.2](#42-登録確認) でパラメータ名を確認 |
| `ModuleNotFoundError: No module named 'feedparser'` | Layer が未紐付けまたはビルド失敗 | [7.3](#73-layer-を-lambda-関数に紐付け) を再実施。Layer が `python3.13` 向けかも確認 |
| `Task timed out after 300.00 seconds` | 外部 API の応答が遅い | 一時的な問題の可能性大。再実行して確認 |
| `[FETCH] TechCrunch: failed ..., skipping` | Cloudflare 等による IP ブロック | 一部ソースが失敗しても他ソースで継続するため、5 件取得できていれば問題なし |

---

## 10. EventBridge スケジュールの有効化

毎朝 6:00 JST に Lambda を自動実行するスケジュールを設定する。

> 詳細手順は `03_詳細設計/01_AWSセットアップ手順書.md` STEP 9 を参照。

### 10.1 スケジュールの作成

1. AWS コンソール → **EventBridge** → 左メニュー「スケジューラ」→「スケジュール」→「スケジュールの作成」

| 設定項目 | 値 |
|---------|---|
| スケジュール名 | `newsbot-daily-6am` |
| スケジュールのパターン | Cron ベース |
| Cron 式 | `0 21 * * ? *` |
| タイムゾーン | Asia/Tokyo |
| フレキシブルな時間枠 | オフ |
| ターゲット | AWS Lambda - Invoke |
| Lambda 関数 | `newsbot-delivery` |
| 最大試行回数 | 2 |
| 実行ロール | このスケジュール用の新しいロールを作成 |

> **Cron 式の解説:** UTC 21:00 = JST 翌 06:00

### 10.2 スケジュール有効化の確認

```bash
aws scheduler get-schedule \
  --name newsbot-daily-6am \
  --region ap-northeast-1 \
  --profile newsbot \
  --query "{State:State, ScheduleExpression:ScheduleExpression, Target:Target.Arn}"
```

**期待する出力:**

```json
{
    "State": "ENABLED",
    "ScheduleExpression": "cron(0 21 * * ? *)",
    "Target": "arn:aws:lambda:ap-northeast-1:123456789012:function:newsbot-delivery"
}
```

### 10.3 翌朝の自動実行確認

翌朝 6:05 JST 以降に以下を確認する。

```bash
# 最新の Lambda 実行ログを確認
aws logs describe-log-streams \
  --log-group-name /aws/lambda/newsbot-delivery \
  --order-by LastEventTime \
  --descending \
  --max-items 3 \
  --region ap-northeast-1 \
  --profile newsbot \
  --query "logStreams[*].{Stream:logStreamName,LastEvent:lastEventTimestamp}"
```

---

## 付録：コードを更新した場合の再デプロイ

コードを修正した際は以下の手順でデプロイする。Layer の変更がなければ [A.1](#a1-アプリコードのみ更新) だけでよい。

### A.1 アプリコードのみ更新

```bash
cd NewsBot/newsbot

zip newsbot-app.zip \
  lambda_function.py ssm_client.py news_fetcher.py \
  ai_ranker.py discord_notifier.py models.py config.py

aws lambda update-function-code \
  --function-name newsbot-delivery \
  --zip-file fileb://newsbot-app.zip \
  --region ap-northeast-1 \
  --profile newsbot
```

### A.2 Layer も更新する場合

`requirements.txt` のライブラリを変更した場合は [STEP 6](#6-lambda-layer-のビルドとアップロード) からやり直す。
新しい Layer バージョンが発行されるため [7.3](#73-layer-を-lambda-関数に紐付け) の Layer 紐付けも再実施すること。

---

## 改訂履歴

| バージョン | 日付 | 変更内容 |
|-----------|------|---------|
| v1.0 | 2026/06/21 | 初版作成 |
