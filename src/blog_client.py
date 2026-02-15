"""Fetch recent posts from tech company blogs via RSS feeds."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import feedparser
from dateutil.parser import parse as parse_date

from config import BLOG_FEEDS, FETCH_HOURS, SAFETY_FEEDS

logger = logging.getLogger(__name__)

# Matches arXiv IDs like 2501.01234 or 2501.01234v2 in URLs and text
_ARXIV_ID_RE = re.compile(r"(?:arxiv\.org/abs/|arxiv\.org/pdf/)?((\d{4}\.\d{4,5})(?:v\d+)?)")

# Simple HTML tag stripper
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """Remove HTML tags from text."""
    return _HTML_TAG_RE.sub("", text).strip()


def _extract_arxiv_ids(text: str) -> list[str]:
    """Extract unique arXiv IDs (without version suffix) from text."""
    ids: list[str] = []
    seen: set[str] = set()
    for match in _ARXIV_ID_RE.finditer(text):
        aid = match.group(2)  # ID without version
        if aid not in seen:
            ids.append(aid)
            seen.add(aid)
    return ids


def _parse_entry(entry: dict[str, Any], source: str) -> dict[str, Any] | None:
    """Parse a single feed entry into a blog post dict."""
    title = entry.get("title", "").strip()
    link = entry.get("link", "")
    if not title or not link:
        return None

    # Parse published date
    published_str = entry.get("published", entry.get("updated", ""))
    published: datetime | None = None
    if published_str:
        try:
            published = parse_date(published_str)
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
        except (ValueError, OverflowError):
            published = None

    # Filter by recency — only posts within FETCH_HOURS
    if published:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=FETCH_HOURS)
        if published < cutoff:
            return None

    # Collect text content to search for arXiv IDs
    content_parts = [link]
    summary = entry.get("summary", "")
    if summary:
        content_parts.append(summary)
    # Some feeds use content[0].value
    content_list = entry.get("content", [])
    for c in content_list:
        if isinstance(c, dict) and c.get("value"):
            content_parts.append(c["value"])
    # Also check entry links for arxiv URLs
    for entry_link in entry.get("links", []):
        href = entry_link.get("href", "")
        if href:
            content_parts.append(href)

    combined = " ".join(content_parts)
    arxiv_ids = _extract_arxiv_ids(combined)

    # Clean summary for display
    clean_summary = _strip_html(summary) if summary else ""

    return {
        "title": title,
        "url": link,
        "source": source,
        "published": published.isoformat() if published else "",
        "summary": clean_summary[:600] if clean_summary else "",
        "arxiv_ids": arxiv_ids,
    }


def _fetch_from_feeds(feeds: dict[str, str], label: str) -> list[dict[str, Any]]:
    """Fetch recent posts from the given feeds.

    Returns a list of dicts with keys:
        title, url, source, published, summary, arxiv_ids
    """
    all_posts: list[dict[str, Any]] = []

    for source, feed_url in feeds.items():
        try:
            feed = feedparser.parse(feed_url)
            if feed.bozo and not feed.entries:
                logger.warning(
                    "Feed %s returned malformed data: %s",
                    source,
                    feed.bozo_exception,
                )
                continue

            for entry in feed.entries:
                post = _parse_entry(entry, source)
                if post is not None:
                    all_posts.append(post)

        except Exception:
            logger.warning("Failed to fetch feed for %s", source, exc_info=True)
            continue

    logger.info("Fetched %d %s posts from %d feeds", len(all_posts), label, len(feeds))
    return all_posts


def fetch_blog_posts() -> list[dict[str, Any]]:
    """Fetch recent posts from all configured blog feeds."""
    return _fetch_from_feeds(BLOG_FEEDS, "blog")


def fetch_safety_posts() -> list[dict[str, Any]]:
    """Fetch recent posts from all configured AI safety feeds."""
    return _fetch_from_feeds(SAFETY_FEEDS, "safety")
