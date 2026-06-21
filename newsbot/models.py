from dataclasses import dataclass


@dataclass(slots=True)
class Article:
    """
    ニュースソースから取得した1件の記事を表すデータモデル。
    """
    title:   str        # 記事タイトル（原文）
    url:     str        # 記事URL
    source:  str        # ソース名（例: "TechCrunch"）
    color:   int        # Discord Embedカラーコード（ソース別）
    summary: str = ""   # Claude AIが生成した日本語要約（初期値は空）
    rank:    int = 0    # AI厳選後の順位（1〜5）


@dataclass(slots=True)
class BotConfig:
    """
    SSM Parameter Storeから取得したシークレット一式。
    """
    anthropic_api_key:    str
    discord_webhook_url:  str
    discord_channel_name: str
