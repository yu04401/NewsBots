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
