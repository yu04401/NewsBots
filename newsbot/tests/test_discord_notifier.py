import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# newsbot/ を sys.path に追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from discord_notifier import send, _build_payload
from models import Article, BotConfig


def _make_articles(n=5):
    return [
        Article(
            title=f"Article {i}",
            url=f"https://example.com/{i}",
            source="TechCrunch",
            color=0x33CC44,
            rank=i + 1,
            summary=f"これは記事{i}の要約です。",
        )
        for i in range(n)
    ]


def _make_config():
    return BotConfig(
        anthropic_api_key="test-api-key",
        discord_webhook_url="https://discord.com/api/webhooks/test/token",
        discord_channel_name="it-news",
    )


class TestBuildPayload(unittest.TestCase):

    def test_payload_structure(self):
        """ペイロードに必要なフィールドが含まれる"""
        articles = _make_articles(3)
        payload = _build_payload(articles)

        self.assertIn("username", payload)
        self.assertIn("content", payload)
        self.assertIn("embeds", payload)
        self.assertEqual(len(payload["embeds"]), 3)

    def test_embed_fields(self):
        """各 Embed に必要なフィールドが設定される"""
        articles = _make_articles(1)
        payload = _build_payload(articles)
        embed = payload["embeds"][0]

        self.assertEqual(embed["title"], articles[0].title)
        self.assertEqual(embed["url"], articles[0].url)
        self.assertEqual(embed["description"], articles[0].summary)
        self.assertEqual(embed["color"], articles[0].color)
        self.assertEqual(embed["footer"]["text"], articles[0].source)

    def test_title_clipped_at_256_chars(self):
        """256文字を超えるタイトルは切り詰められる"""
        long_title = "A" * 300
        articles = [Article(title=long_title, url="https://example.com",
                            source="Test", color=0x000000, rank=1, summary="summary")]
        payload = _build_payload(articles)
        self.assertEqual(len(payload["embeds"][0]["title"]), 256)

    def test_summary_clipped_at_200_chars(self):
        """200文字を超える要約は切り詰められる"""
        long_summary = "要" * 250
        articles = [Article(title="Title", url="https://example.com",
                            source="Test", color=0x000000, rank=1, summary=long_summary)]
        payload = _build_payload(articles)
        self.assertLessEqual(len(payload["embeds"][0]["description"]), 200)

    def test_content_includes_count(self):
        """メッセージ本文に記事件数が含まれる"""
        articles = _make_articles(3)
        payload = _build_payload(articles)
        self.assertIn("TOP3", payload["content"])

    def test_bot_username(self):
        """ボット名が設定される"""
        articles = _make_articles(1)
        payload = _build_payload(articles)
        self.assertEqual(payload["username"], "IT News Bot")


class TestSend(unittest.TestCase):

    @patch("discord_notifier.httpx.Client")
    def test_returns_on_204(self, mock_client_cls):
        """204 レスポンスで正常終了する"""
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.status_code = 204
        mock_client.post.return_value = mock_resp

        articles = _make_articles(5)
        config = _make_config()

        send(articles, config)  # 例外が raise されないことを確認
        mock_client.post.assert_called_once()

    @patch("discord_notifier.time.sleep")
    @patch("discord_notifier.httpx.Client")
    def test_retries_on_429(self, mock_client_cls, mock_sleep):
        """429 レスポンスでリトライし、最終的に Exception を raise する"""
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.request = MagicMock()
        mock_resp.response = mock_resp
        mock_client.post.return_value = mock_resp

        articles = _make_articles(5)
        config = _make_config()

        with self.assertRaises(Exception) as ctx:
            send(articles, config)

        self.assertIn("Failed after", str(ctx.exception))
        # DISCORD_MAX_RETRIES=3 なのでリトライは3回
        self.assertEqual(mock_sleep.call_count, 3)

    @patch("discord_notifier.time.sleep")
    @patch("discord_notifier.httpx.Client")
    def test_retries_on_500(self, mock_client_cls, mock_sleep):
        """5xx レスポンスでリトライし、最終的に Exception を raise する"""
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_resp.request = MagicMock()
        mock_client.post.return_value = mock_resp

        articles = _make_articles(5)
        config = _make_config()

        with self.assertRaises(Exception):
            send(articles, config)

        self.assertEqual(mock_sleep.call_count, 3)

    @patch("discord_notifier.time.sleep")
    @patch("discord_notifier.httpx.Client")
    def test_no_retry_on_400(self, mock_client_cls, mock_sleep):
        """400 レスポンスはリトライせず即座に例外を raise する"""
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.raise_for_status.side_effect = Exception("400 Bad Request")
        mock_client.post.return_value = mock_resp

        articles = _make_articles(5)
        config = _make_config()

        with self.assertRaises(Exception):
            send(articles, config)

        mock_sleep.assert_not_called()

    @patch("discord_notifier.time.sleep")
    @patch("discord_notifier.httpx.Client")
    def test_succeeds_on_retry(self, mock_client_cls, mock_sleep):
        """初回失敗後にリトライで成功する場合は例外が raise されない"""
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        fail_resp = MagicMock()
        fail_resp.status_code = 429
        fail_resp.request = MagicMock()

        success_resp = MagicMock()
        success_resp.status_code = 204

        mock_client.post.side_effect = [fail_resp, success_resp]

        articles = _make_articles(5)
        config = _make_config()

        send(articles, config)  # 例外が raise されないことを確認
        self.assertEqual(mock_client.post.call_count, 2)
        self.assertEqual(mock_sleep.call_count, 1)


if __name__ == "__main__":
    unittest.main()
