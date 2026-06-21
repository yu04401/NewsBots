import time
import logging
import feedparser
import httpx
from models import Article
from config import (
    NEWS_SOURCES,
    MAX_ARTICLES_PER_SOURCE,
    FETCH_TIMEOUT_SEC,
    FETCH_MAX_RETRIES,
    FETCH_RETRY_WAIT_SEC,
)

logger = logging.getLogger(__name__)


def fetch_all_articles() -> list[Article]:
    """
    全ソースから記事を取得し、URL重複を除去して返す。
    一部ソースの失敗は警告ログに記録して処理を継続する。
    """
    all_articles: list[Article] = []
    seen_urls: set[str] = set()

    for source in NEWS_SOURCES:
        try:
            if source["type"] == "hackernews":
                articles = _fetch_hackernews(source)
            else:
                articles = _fetch_rss(source)

            logger.info(f"[FETCH] {source['name']}: {len(articles)} articles fetched")

            for article in articles:
                if article.url not in seen_urls:
                    seen_urls.add(article.url)
                    all_articles.append(article)

        except Exception as e:
            logger.warning(f"[FETCH] {source['name']}: failed ({e}), skipping")

    return all_articles


def _fetch_rss(source: dict) -> list[Article]:
    """
    RSS/AtomフィードをfeedparserでパースしてArticleリストを返す。
    最大 MAX_ARTICLES_PER_SOURCE 件を返す。
    """
    for attempt in range(FETCH_MAX_RETRIES + 1):
        try:
            feed = feedparser.parse(
                source["url"],
                request_headers={"User-Agent": "NewsBot/1.0"},
            )

            # feedparserはネットワーク失敗時にbozo=1を立てる
            if feed.bozo and len(feed.entries) == 0:
                raise ValueError(f"Feed parse error: {feed.bozo_exception}")

            articles = []
            for entry in feed.entries[:MAX_ARTICLES_PER_SOURCE]:
                url   = getattr(entry, "link", "")
                title = getattr(entry, "title", "")
                if not url or not title:
                    continue
                articles.append(Article(
                    title=title.strip(),
                    url=url.strip(),
                    source=source["name"],
                    color=source["color"],
                ))
            return articles

        except Exception as e:
            if attempt < FETCH_MAX_RETRIES:
                logger.warning(f"[FETCH] {source['name']}: retry {attempt + 1} ({e})")
                time.sleep(FETCH_RETRY_WAIT_SEC)
            else:
                raise


def _fetch_hackernews(source: dict) -> list[Article]:
    """
    Hacker News APIからトップ記事を取得してArticleリストを返す。
    トップ記事IDを取得 → 上位 MAX_ARTICLES_PER_SOURCE 件の詳細を取得する。
    """
    base_url = "https://hacker-news.firebaseio.com/v0"

    with httpx.Client(timeout=FETCH_TIMEOUT_SEC) as client:
        resp = client.get(f"{base_url}/topstories.json")
        resp.raise_for_status()
        top_ids: list[int] = resp.json()[:MAX_ARTICLES_PER_SOURCE]

        articles = []
        for item_id in top_ids:
            try:
                resp = client.get(f"{base_url}/item/{item_id}.json")
                resp.raise_for_status()
                item = resp.json()

                url   = item.get("url", "")
                title = item.get("title", "")
                if not url or not title:
                    continue  # Ask HNなどURLなし記事はスキップ

                articles.append(Article(
                    title=title.strip(),
                    url=url.strip(),
                    source=source["name"],
                    color=source["color"],
                ))
            except Exception:
                continue  # 個別記事の失敗はスキップして継続

    return articles
