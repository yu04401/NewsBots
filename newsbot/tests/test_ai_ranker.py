import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# newsbot/ を sys.path に追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ai_ranker import rank_and_summarize, _build_prompt, _parse_response
from models import Article, BotConfig


def _make_articles(n=5):
    return [
        Article(
            title=f"Article {i}",
            url=f"https://example.com/{i}",
            source="TechCrunch",
            color=0x33CC44,
        )
        for i in range(n)
    ]


def _make_config():
    return BotConfig(
        anthropic_api_key="test-api-key",
        discord_webhook_url="https://discord.com/api/webhooks/test",
        discord_channel_name="it-news",
    )


class TestBuildPrompt(unittest.TestCase):

    def test_includes_all_articles(self):
        """プロンプトに全記事のタイトルとURLが含まれる"""
        articles = _make_articles(3)
        prompt = _build_prompt(articles)
        for i, article in enumerate(articles):
            self.assertIn(f"[{i}]", prompt)
            self.assertIn(article.title, prompt)
            self.assertIn(article.url, prompt)

    def test_uses_zero_based_index(self):
        """0始まりのインデックスを使用する"""
        articles = _make_articles(2)
        prompt = _build_prompt(articles)
        self.assertIn("[0]", prompt)
        self.assertIn("[1]", prompt)


class TestParseResponse(unittest.TestCase):

    def test_parse_valid_json(self):
        """正常なJSONレスポンスをパースして Article に rank・summary を設定する"""
        articles = _make_articles(10)
        response_text = """
[
  {"index": 2, "rank": 1, "summary": "記事2の要約です。"},
  {"index": 5, "rank": 2, "summary": "記事5の要約です。"},
  {"index": 0, "rank": 3, "summary": "記事0の要約です。"},
  {"index": 8, "rank": 4, "summary": "記事8の要約です。"},
  {"index": 1, "rank": 5, "summary": "記事1の要約です。"}
]
"""
        result = _parse_response(response_text, articles)

        self.assertEqual(len(result), 5)
        # rank 順に並んでいることを確認
        self.assertEqual(result[0].rank, 1)
        self.assertEqual(result[0].title, "Article 2")
        self.assertEqual(result[0].summary, "記事2の要約です。")
        self.assertEqual(result[1].rank, 2)
        self.assertEqual(result[1].title, "Article 5")

    def test_parse_json_with_surrounding_text(self):
        """JSONの前後に余分なテキストがあっても抽出できる"""
        articles = _make_articles(3)
        response_text = """こちらがトップ3件です：
[
  {"index": 0, "rank": 1, "summary": "要約0"},
  {"index": 1, "rank": 2, "summary": "要約1"},
  {"index": 2, "rank": 3, "summary": "要約2"}
]
以上です。"""
        result = _parse_response(response_text, articles)
        self.assertEqual(len(result), 3)

    def test_raises_on_no_json_array(self):
        """JSON配列が含まれないレスポンスは ValueError を raise する"""
        articles = _make_articles(3)
        with self.assertRaises(ValueError) as ctx:
            _parse_response("これはJSONではありません", articles)
        self.assertIn("does not contain JSON array", str(ctx.exception))

    def test_raises_on_invalid_json(self):
        """不正なJSONは json.JSONDecodeError を raise する"""
        articles = _make_articles(3)
        with self.assertRaises(Exception):
            _parse_response("[{invalid json}]", articles)

    def test_raises_on_index_out_of_range(self):
        """存在しないインデックスを参照すると ValueError を raise する"""
        articles = _make_articles(3)
        response_text = '[{"index": 99, "rank": 1, "summary": "out of range"}]'
        with self.assertRaises(ValueError) as ctx:
            _parse_response(response_text, articles)
        self.assertIn("out of range", str(ctx.exception))

    def test_raises_on_negative_index(self):
        """負のインデックスは ValueError を raise する"""
        articles = _make_articles(3)
        response_text = '[{"index": -1, "rank": 1, "summary": "negative index"}]'
        with self.assertRaises(ValueError):
            _parse_response(response_text, articles)


class TestRankAndSummarize(unittest.TestCase):

    @patch("ai_ranker.Anthropic")
    def test_calls_claude_and_returns_ranked_articles(self, mock_anthropic_cls):
        """Claude APIを呼び出して厳選済み記事リストを返す"""
        articles = _make_articles(10)
        config = _make_config()

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = """[
  {"index": 0, "rank": 1, "summary": "要約0"},
  {"index": 1, "rank": 2, "summary": "要約1"},
  {"index": 2, "rank": 3, "summary": "要約2"},
  {"index": 3, "rank": 4, "summary": "要約3"},
  {"index": 4, "rank": 5, "summary": "要約4"}
]"""
        mock_client.messages.create.return_value = mock_response

        result = rank_and_summarize(articles, config)

        self.assertEqual(len(result), 5)
        mock_anthropic_cls.assert_called_once_with(api_key="test-api-key")
        mock_client.messages.create.assert_called_once()

    @patch("ai_ranker.Anthropic")
    def test_propagates_api_error(self, mock_anthropic_cls):
        """Claude API 呼び出し失敗時は例外をそのまま伝播させる"""
        articles = _make_articles(5)
        config = _make_config()

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.side_effect = Exception("API connection error")

        with self.assertRaises(Exception) as ctx:
            rank_and_summarize(articles, config)
        self.assertIn("API connection error", str(ctx.exception))

    @patch("ai_ranker.Anthropic")
    def test_propagates_parse_error(self, mock_anthropic_cls):
        """レスポンスのパース失敗時は ValueError を伝播させる"""
        articles = _make_articles(5)
        config = _make_config()

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = "申し訳ありませんが、JSON形式での出力ができません。"
        mock_client.messages.create.return_value = mock_response

        with self.assertRaises(ValueError):
            rank_and_summarize(articles, config)


if __name__ == "__main__":
    unittest.main()
