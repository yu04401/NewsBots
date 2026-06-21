import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# newsbot/ を sys.path に追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from news_fetcher import fetch_all_articles, _fetch_rss, _fetch_hackernews
from models import Article


def _make_source(name="TestRSS", source_type="rss", url="https://example.com/feed", color=0x123456):
    return {"name": name, "type": source_type, "url": url, "color": color}


class TestFetchRss(unittest.TestCase):

    def _make_entry(self, title="Test Title", link="https://example.com/article"):
        entry = MagicMock()
        entry.title = title
        entry.link = link
        return entry

    @patch("news_fetcher.feedparser.parse")
    def test_returns_articles_on_success(self, mock_parse):
        """正常なRSSフィードから記事リストが返される"""
        feed = MagicMock()
        feed.bozo = False
        feed.entries = [self._make_entry("Article A", "https://example.com/a")]
        mock_parse.return_value = feed

        source = _make_source()
        result = _fetch_rss(source)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].title, "Article A")
        self.assertEqual(result[0].url, "https://example.com/a")
        self.assertEqual(result[0].source, "TestRSS")

    @patch("news_fetcher.feedparser.parse")
    def test_skips_entries_without_url_or_title(self, mock_parse):
        """URL またはタイトルが空のエントリはスキップされる"""
        feed = MagicMock()
        feed.bozo = False
        entry_no_url = MagicMock()
        entry_no_url.title = "No URL article"
        entry_no_url.link = ""
        entry_no_title = MagicMock()
        entry_no_title.title = ""
        entry_no_title.link = "https://example.com/notitle"
        feed.entries = [entry_no_url, entry_no_title]
        mock_parse.return_value = feed

        result = _fetch_rss(_make_source())
        self.assertEqual(result, [])

    @patch("news_fetcher.time.sleep")
    @patch("news_fetcher.feedparser.parse")
    def test_retries_on_bozo_empty_feed(self, mock_parse, mock_sleep):
        """bozo=1 かつ entries が空の場合はリトライし、最終的に例外を raise する"""
        feed = MagicMock()
        feed.bozo = True
        feed.bozo_exception = Exception("parse error")
        feed.entries = []
        mock_parse.return_value = feed

        with self.assertRaises(ValueError):
            _fetch_rss(_make_source())

        # FETCH_MAX_RETRIES=2 なので sleep は2回呼ばれる
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("news_fetcher.feedparser.parse")
    def test_bozo_with_entries_does_not_raise(self, mock_parse):
        """bozo=1 でも entries がある場合は正常に記事を返す（警告のみ）"""
        feed = MagicMock()
        feed.bozo = True
        feed.bozo_exception = Exception("minor parse warning")
        feed.entries = [self._make_entry("Article B", "https://example.com/b")]
        mock_parse.return_value = feed

        result = _fetch_rss(_make_source())
        self.assertEqual(len(result), 1)

    @patch("news_fetcher.feedparser.parse")
    def test_respects_max_articles_per_source(self, mock_parse):
        """MAX_ARTICLES_PER_SOURCE を超えた分はスキップされる"""
        feed = MagicMock()
        feed.bozo = False
        feed.entries = [
            self._make_entry(f"Article {i}", f"https://example.com/{i}")
            for i in range(30)
        ]
        mock_parse.return_value = feed

        result = _fetch_rss(_make_source())
        # MAX_ARTICLES_PER_SOURCE = 20
        self.assertLessEqual(len(result), 20)


class TestFetchHackernews(unittest.TestCase):

    @patch("news_fetcher.httpx.Client")
    def test_returns_articles_on_success(self, mock_client_cls):
        """正常なHN APIレスポンスから記事リストが返される"""
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        top_ids_resp = MagicMock()
        top_ids_resp.json.return_value = [1, 2]
        top_ids_resp.raise_for_status = MagicMock()

        item1_resp = MagicMock()
        item1_resp.json.return_value = {"title": "HN Article 1", "url": "https://hn.com/1"}
        item1_resp.raise_for_status = MagicMock()

        item2_resp = MagicMock()
        item2_resp.json.return_value = {"title": "HN Article 2", "url": "https://hn.com/2"}
        item2_resp.raise_for_status = MagicMock()

        mock_client.get.side_effect = [top_ids_resp, item1_resp, item2_resp]

        source = _make_source(name="Hacker News", source_type="hackernews")
        result = _fetch_hackernews(source)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].title, "HN Article 1")

    @patch("news_fetcher.httpx.Client")
    def test_skips_items_without_url(self, mock_client_cls):
        """URL のない記事（Ask HN など）はスキップされる"""
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        top_ids_resp = MagicMock()
        top_ids_resp.json.return_value = [1]
        top_ids_resp.raise_for_status = MagicMock()

        item_resp = MagicMock()
        item_resp.json.return_value = {"title": "Ask HN: something", "url": ""}
        item_resp.raise_for_status = MagicMock()

        mock_client.get.side_effect = [top_ids_resp, item_resp]

        source = _make_source(name="Hacker News", source_type="hackernews")
        result = _fetch_hackernews(source)

        self.assertEqual(result, [])

    @patch("news_fetcher.httpx.Client")
    def test_continues_on_individual_item_failure(self, mock_client_cls):
        """個別記事の取得失敗は無視して他の記事を処理する"""
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        top_ids_resp = MagicMock()
        top_ids_resp.json.return_value = [1, 2]
        top_ids_resp.raise_for_status = MagicMock()

        item1_resp = MagicMock()
        item1_resp.raise_for_status.side_effect = Exception("network error")

        item2_resp = MagicMock()
        item2_resp.json.return_value = {"title": "HN Article 2", "url": "https://hn.com/2"}
        item2_resp.raise_for_status = MagicMock()

        mock_client.get.side_effect = [top_ids_resp, item1_resp, item2_resp]

        source = _make_source(name="Hacker News", source_type="hackernews")
        result = _fetch_hackernews(source)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].title, "HN Article 2")


class TestFetchAllArticles(unittest.TestCase):

    @patch("news_fetcher.NEWS_SOURCES", [
        {"name": "RSS1", "type": "rss", "url": "https://rss1.com/feed", "color": 0x111111},
        {"name": "HN",   "type": "hackernews", "url": "https://hn.com", "color": 0x222222},
    ])
    @patch("news_fetcher._fetch_hackernews")
    @patch("news_fetcher._fetch_rss")
    def test_deduplicates_urls(self, mock_rss, mock_hn):
        """同じ URL が複数ソースから返された場合、重複を除去する"""
        duplicate_article = Article(title="Dup", url="https://shared.com/article",
                                    source="RSS1", color=0x111111)
        mock_rss.return_value = [duplicate_article]
        mock_hn.return_value = [
            Article(title="Dup HN", url="https://shared.com/article",
                    source="HN", color=0x222222),
            Article(title="Unique", url="https://unique.com/article",
                    source="HN", color=0x222222),
        ]

        result = fetch_all_articles()
        urls = [a.url for a in result]
        self.assertEqual(len(urls), len(set(urls)))  # 重複なし
        self.assertEqual(len(result), 2)

    @patch("news_fetcher.NEWS_SOURCES", [
        {"name": "BrokenRSS", "type": "rss", "url": "https://broken.com/feed", "color": 0x111111},
        {"name": "GoodRSS",   "type": "rss", "url": "https://good.com/feed", "color": 0x222222},
    ])
    @patch("news_fetcher._fetch_rss")
    def test_continues_on_source_failure(self, mock_rss):
        """一部ソースが失敗しても他のソースを処理し、空リストは返さない"""
        def side_effect(source):
            if source["name"] == "BrokenRSS":
                raise Exception("timeout")
            return [Article(title="Good Article", url="https://good.com/a",
                            source="GoodRSS", color=0x222222)]

        mock_rss.side_effect = side_effect
        result = fetch_all_articles()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].source, "GoodRSS")

    @patch("news_fetcher.NEWS_SOURCES", [
        {"name": "EmptyRSS", "type": "rss", "url": "https://empty.com/feed", "color": 0x111111},
    ])
    @patch("news_fetcher._fetch_rss")
    def test_returns_empty_list_when_all_fail(self, mock_rss):
        """全ソースが失敗した場合は空リストを返す"""
        mock_rss.side_effect = Exception("all failed")
        result = fetch_all_articles()
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
