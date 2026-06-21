import os
import logging
import boto3
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

    LOCAL_TEST=1 環境変数が設定されている場合は、環境変数から直接読み込む
    （ローカルテスト用フォールバック）。

    Raises:
        Exception: パラメータ取得に失敗した場合
    """
    if os.environ.get("LOCAL_TEST") == "1":
        logger.info("[SSM] LOCAL_TEST mode: reading from environment variables")
        return BotConfig(
            anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
            discord_webhook_url=os.environ["DISCORD_WEBHOOK_URL"],
            discord_channel_name=os.environ.get("DISCORD_CHANNEL_NAME", "it-news"),
        )

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
