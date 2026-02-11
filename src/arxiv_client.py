"""Fetch recent papers from arXiv API (Atom feed)."""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import feedparser
import requests
from dateutil.parser import parse as parse_date

from config import (
    ARXIV_API_URL,
    ARXIV_CATEGORIES,
    FETCH_HOURS,
    KEYWORD_PATTERNS,
    MAX_RESULTS,
)

logger = logging.getLogger(__name__)

# Retry settings for transient arXiv API failures
_MAX_RETRIES = 3
_RETRY_DELAY_SECONDS = 5


def _extract_arxiv_id(entry: dict[str, Any]) -> str:
    """Extract the short arXiv ID (e.g. '2501.01234') from an entry."""
    entry_id: str = entry.get("id", "")
    # id is typically http://arxiv.org/abs/2501.01234v1
    match = re.search(r"(\d{4}\.\d{4,5})(v\d+)?$", entry_id)
    if match:
        return match.group(1)
    # Fallback: return the full id URL to avoid silent drops
    return entry_id


def _extract_categories(entry: dict[str, Any]) -> list[str]:
    """Extract category terms from an entry."""
    tags = entry.get("tags", [])
    return [t.get("term", "") for t in tags if t.get("term")]


def _extract_authors(entry: dict[str, Any]) -> list[str]:
    """Extract author names from an entry."""
    authors = entry.get("authors", [])
    return [a.get("name", "") for a in authors if a.get("name")]


def _extract_link(entry: dict[str, Any]) -> str:
    """Extract the HTML link for the paper."""
    links = entry.get("links", [])
    for link in links:
        if link.get("type") == "text/html":
            return link.get("href", "")
    # Fallback to first link or id
    if links:
        return links[0].get("href", "")
    return entry.get("id", "")


def _match_keywords(title: str, summary: str, authors: list[str]) -> list[str]:
    """Return list of matched company keywords using regex word boundaries."""
    combined = f"{title} {summary} {' '.join(authors)}"
    matched = []
    seen: set[str] = set()
    for display, pattern in KEYWORD_PATTERNS:
        if display not in seen and pattern.search(combined):
            matched.append(display)
            seen.add(display)
    return matched


def _build_query() -> str:
    """Build the arXiv API search query string for target categories."""
    cat_parts = [f"cat:{cat}" for cat in ARXIV_CATEGORIES]
    return "+OR+".join(cat_parts)


def _fetch_feed(url: str) -> feedparser.FeedParserDict:
    """Fetch the arXiv Atom feed with retries on transient failures.

    Uses ``requests`` for HTTP-level error handling, then passes the
    response body to ``feedparser`` for XML parsing.
    """
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as exc:
            last_exc = exc
            logger.warning(
                "arXiv API request failed (attempt %d/%d): %s",
                attempt, _MAX_RETRIES, exc,
            )
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY_SECONDS * attempt)
            continue

        feed = feedparser.parse(resp.text)
        if feed.bozo and not feed.entries:
            last_exc = RuntimeError(
                f"arXiv API returned malformed feed: {feed.bozo_exception}"
            )
            logger.warning(
                "arXiv API returned unparseable response (attempt %d/%d): %s",
                attempt, _MAX_RETRIES, feed.bozo_exception,
            )
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY_SECONDS * attempt)
            continue

        return feed

    raise RuntimeError(
        f"arXiv API failed after {_MAX_RETRIES} attempts: {last_exc}"
    )


def fetch_recent_papers() -> list[dict[str, Any]]:
    """Fetch papers from the last FETCH_HOURS and return matched ones.

    Returns a list of dicts with keys:
        arxiv_id, title, summary, authors, link, published, categories, matched_keywords
    """
    query = _build_query()
    url = f"{ARXIV_API_URL}?search_query={query}&sortBy=submittedDate&sortOrder=descending&max_results={MAX_RESULTS}"

    feed = _fetch_feed(url)

    cutoff = datetime.now(timezone.utc) - timedelta(hours=FETCH_HOURS)
    results: list[dict[str, Any]] = []

    for entry in feed.entries:
        # Parse published date
        published_str = entry.get("published", "")
        if not published_str:
            continue
        try:
            published = parse_date(published_str)
        except (ValueError, OverflowError):
            continue

        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)

        if published < cutoff:
            continue

        title = entry.get("title", "").replace("\n", " ").strip()
        summary = entry.get("summary", "").replace("\n", " ").strip()
        authors = _extract_authors(entry)
        matched = _match_keywords(title, summary, authors)

        if not matched:
            continue

        results.append(
            {
                "arxiv_id": _extract_arxiv_id(entry),
                "title": title,
                "summary": summary,
                "authors": authors,
                "link": _extract_link(entry),
                "published": published.isoformat(),
                "categories": _extract_categories(entry),
                "matched_keywords": matched,
            }
        )

    # Be polite to arXiv API
    time.sleep(1)

    return results
