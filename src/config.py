"""Configuration constants for Research Briefing Bot."""

import os
import re
from datetime import timedelta, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load .env from project root (parent of src/)
load_dotenv(_PROJECT_ROOT / ".env")

# arXiv API
ARXIV_API_URL = "https://export.arxiv.org/api/query"
FETCH_HOURS = 48  # Look back window in hours
MAX_RESULTS = 200  # Max papers per API call

# Slack (Bot Token + Channel ID)
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID", "")

# Output directory for generated briefing files (Markdown / PDF)
OUT_DIR = _PROJECT_ROOT / "out"

# State file
STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "state.json")

# Display limits
MAX_AUTHORS_DISPLAY = 6
MAX_SUMMARY_LENGTH = 600

# Blog state retention (days)
BLOG_RETENTION_DAYS = 30

# Daily buffer retention (days) — briefing consumes buffer, this is a safety net
BUFFER_RETENTION_DAYS = 3

# JST timezone for daily briefing date keys and headers
JST = timezone(timedelta(hours=9))


# ---------------------------------------------------------------------------
# Tracking config: loaded from config.yml (falls back to hardcoded defaults)
# ---------------------------------------------------------------------------

_DEFAULT_CATEGORIES = ["cs.AI", "cs.LG", "stat.ML"]

_DEFAULT_BLOG_FEEDS: dict[str, str] = {
    "Google Research": "https://blog.research.google/feeds/posts/default?alt=rss",
    "DeepMind": "https://deepmind.google/blog/rss.xml",
    "OpenAI": "https://openai.com/blog/rss.xml",
}

_DEFAULT_SAFETY_FEEDS: dict[str, str] = {}

_DEFAULT_KEYWORDS: list[tuple[str, re.Pattern[str]]] = [
    ("Google", re.compile(r"\bGoogle\b", re.IGNORECASE)),
    ("DeepMind", re.compile(r"\bDeepMind\b", re.IGNORECASE)),
    ("Meta", re.compile(r"\bMeta\b")),
    ("FAIR", re.compile(r"\bFAIR\b")),
    ("FAIR", re.compile(r"\bFacebook\ AI\ Research\b", re.IGNORECASE)),
    ("OpenAI", re.compile(r"\bOpenAI\b", re.IGNORECASE)),
    ("Anthropic", re.compile(r"\bAnthropic\b", re.IGNORECASE)),
]


def _compile_keywords(raw: list[dict]) -> list[tuple[str, re.Pattern[str]]]:
    """Compile keyword entries from config YAML into (display_name, pattern) tuples.

    By default, pattern values are treated as plain strings: they are escaped
    with ``re.escape`` and wrapped in word boundaries (``\\b...\\b``).
    Set ``raw_regex: true`` on an entry to use the pattern as a raw regular
    expression without escaping or automatic word boundaries.
    """
    result: list[tuple[str, re.Pattern[str]]] = []
    for entry in raw:
        if "label" not in entry or "pattern" not in entry:
            raise ValueError(f"Keyword entry must have 'label' and 'pattern': {entry}")
        display = entry.get("display_as", entry["label"])
        flags = 0 if entry.get("case_sensitive", False) else re.IGNORECASE

        raw_pattern = entry["pattern"]
        if entry.get("raw_regex", False):
            regex_str = raw_pattern
        else:
            regex_str = r"\b" + re.escape(raw_pattern) + r"\b"

        try:
            compiled = re.compile(regex_str, flags)
        except re.error as exc:
            raise ValueError(
                f"Invalid regex for keyword '{entry['label']}': "
                f"pattern={raw_pattern!r}, compiled={regex_str!r} — {exc}"
            ) from exc

        result.append((display, compiled))
    return result


def _load_tracking_config() -> (
    tuple[list[str], dict[str, str], dict[str, str], list[tuple[str, re.Pattern[str]]]]
):
    """Load tracking config from YAML, falling back to hardcoded defaults.

    Resolution order:
      1. config.yml        (user customisation, gitignored)
      2. config.example.yml (shipped defaults)
      3. hardcoded defaults (if neither file exists)
    """
    config_path = _PROJECT_ROOT / "config.yml"
    if not config_path.exists():
        config_path = _PROJECT_ROOT / "config.example.yml"
    if not config_path.exists():
        return _DEFAULT_CATEGORIES, _DEFAULT_BLOG_FEEDS, _DEFAULT_SAFETY_FEEDS, _DEFAULT_KEYWORDS

    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"{config_path.name} must be a YAML mapping, got {type(data).__name__}")

    # --- arxiv_categories ---
    categories = data.get("arxiv_categories", _DEFAULT_CATEGORIES)
    if not isinstance(categories, list) or not all(isinstance(c, str) for c in categories):
        raise ValueError("arxiv_categories must be a list of strings")

    # --- blog_feeds ---
    raw_feeds = data.get("blog_feeds")
    if raw_feeds is None:
        feeds = dict(_DEFAULT_BLOG_FEEDS)
    else:
        if not isinstance(raw_feeds, list):
            raise ValueError("blog_feeds must be a list of {source, url} mappings")
        feeds: dict[str, str] = {}
        for entry in raw_feeds:
            if not isinstance(entry, dict) or "source" not in entry or "url" not in entry:
                raise ValueError(f"blog_feeds entry must have 'source' and 'url': {entry}")
            feeds[entry["source"]] = entry["url"]

    # --- safety_feeds ---
    raw_safety = data.get("safety_feeds")
    if raw_safety is None:
        safety_feeds = dict(_DEFAULT_SAFETY_FEEDS)
    else:
        if not isinstance(raw_safety, list):
            raise ValueError("safety_feeds must be a list of {source, url} mappings")
        safety_feeds: dict[str, str] = {}
        for entry in raw_safety:
            if not isinstance(entry, dict) or "source" not in entry or "url" not in entry:
                raise ValueError(f"safety_feeds entry must have 'source' and 'url': {entry}")
            safety_feeds[entry["source"]] = entry["url"]

    # --- keywords ---
    raw_keywords = data.get("keywords")
    if raw_keywords is None:
        keywords = list(_DEFAULT_KEYWORDS)
    else:
        if not isinstance(raw_keywords, list):
            raise ValueError("keywords must be a list of keyword entries")
        keywords = _compile_keywords(raw_keywords)

    return categories, feeds, safety_feeds, keywords


ARXIV_CATEGORIES, BLOG_FEEDS, SAFETY_FEEDS, KEYWORD_PATTERNS = _load_tracking_config()
