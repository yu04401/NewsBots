# ---- SSM パラメータ名 ----
SSM_ANTHROPIC_API_KEY     = "/newsbot/anthropic_api_key"
SSM_DISCORD_WEBHOOK_URL   = "/newsbot/discord_webhook_url"
SSM_DISCORD_CHANNEL_NAME  = "/newsbot/discord_channel_name"

# ---- AWS ----
AWS_REGION = "ap-northeast-1"

# ---- Claude AI ----
CLAUDE_MODEL       = "claude-haiku-4-5"
CLAUDE_MAX_TOKENS  = 2048
CLAUDE_TEMPERATURE = 0.3
TOP_N_ARTICLES     = 5          # 配信する記事件数

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
