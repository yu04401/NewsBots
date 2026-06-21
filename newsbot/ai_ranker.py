import json
import logging
import re
from anthropic import Anthropic
from models import Article, BotConfig
from config import (
    CLAUDE_MODEL,
    CLAUDE_MAX_TOKENS,
    CLAUDE_TEMPERATURE,
    TOP_N_ARTICLES,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """あなたはIT・テクノロジー分野の優秀なニュースキュレーターです。
与えられた記事リストから、以下の基準でトップ{n}件を厳選してください。

厳選基準：
- IT・テクノロジーの重要度・インパクト
- 新規性・話題性
- エンジニアやIT従事者への関連性

必ず以下のJSON形式のみで出力してください。説明文や前置きは不要です：
[
  {{
    "index": 記事リストの0始まりインデックス（整数）,
    "rank": 順位（1が最重要）,
    "summary": "1〜2文の日本語要約。元記事が英語でも日本語で書くこと。"
  }}
]"""


def rank_and_summarize(articles: list[Article], config: BotConfig) -> list[Article]:
    """
    Claude AIで記事を厳選・要約する。

    Args:
        articles: 重複除去済みの全記事リスト
        config:   APIキーを含む設定

    Returns:
        rankとsummaryが設定されたArticleリスト（TOP_N_ARTICLES件以下）

    Raises:
        Exception: Claude API呼び出し失敗、またはレスポンスパース失敗
    """
    client = Anthropic(api_key=config.anthropic_api_key)

    user_prompt = _build_prompt(articles)
    system = SYSTEM_PROMPT.format(n=TOP_N_ARTICLES)

    logger.info(f"[AI] Sending {len(articles)} articles to Claude for ranking")

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=CLAUDE_MAX_TOKENS,
        temperature=CLAUDE_TEMPERATURE,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
    )

    response_text = response.content[0].text
    ranked = _parse_response(response_text, articles)

    return ranked


def _build_prompt(articles: list[Article]) -> str:
    """
    記事リストをClaudeに渡すプロンプト文字列に変換する。

    出力例:
        以下の記事リストからトップ5件を厳選・要約してください：

        [0] TechCrunch | OpenAI Releases GPT-5
            URL: https://techcrunch.com/...
        [1] Zenn | Pythonで始めるLLM開発
            URL: https://zenn.dev/...
    """
    lines = ["以下の記事リストからトップ5件を厳選・要約してください：\n"]
    for i, article in enumerate(articles):
        lines.append(f"[{i}] {article.source} | {article.title}")
        lines.append(f"    URL: {article.url}")
    return "\n".join(lines)


def _parse_response(response_text: str, articles: list[Article]) -> list[Article]:
    """
    ClaudeのレスポンスJSONをパースし、元のArticleオブジェクトに
    rank と summary を設定して返す。

    Raises:
        ValueError: JSONパース失敗またはindexが範囲外の場合
    """
    # Claudeが余分な文字を含む場合に備えてJSON配列部分を抽出
    json_match = re.search(r"\[.*\]", response_text, re.DOTALL)
    if not json_match:
        raise ValueError(f"Claude response does not contain JSON array: {response_text[:200]}")

    ranked_data: list[dict] = json.loads(json_match.group())

    result: list[Article] = []
    for item in sorted(ranked_data, key=lambda x: x["rank"]):
        idx = item["index"]
        if not (0 <= idx < len(articles)):
            raise ValueError(f"Article index {idx} out of range (total: {len(articles)})")

        article = articles[idx]
        article.rank = item["rank"]
        article.summary = item["summary"]
        result.append(article)

    return result
