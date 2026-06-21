import json
import logging
from ssm_client import get_config
from news_fetcher import fetch_all_articles
from ai_ranker import rank_and_summarize
from discord_notifier import send

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event: dict, context: object) -> dict:
    """
    Lambda エントリーポイント。各モジュールを順番に呼び出す。

    Returns:
        {"statusCode": 200, "body": "..."}

    Raises:
        Exception: 各モジュールで発生した例外はそのまま伝播させ、
                   Lambda の失敗ログ（CloudWatch Logs）に記録する。
    """
    logger.info("[START] NewsBot Lambda started")

    # ① シークレット取得
    config = get_config()
    logger.info("[SSM] Parameters loaded successfully")

    # ② ニュース取得
    logger.info("[FETCH] Fetching news from 6 sources")
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


if __name__ == "__main__":
    # ローカル実行用エントリーポイント（LOCAL_TEST=1 環境変数を設定して実行）
    result = lambda_handler({}, None)
    print(result)
