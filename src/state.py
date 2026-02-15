"""State management using a local JSON file for duplicate detection."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from config import BLOG_RETENTION_DAYS, BUFFER_RETENTION_DAYS, FETCH_HOURS, JST, STATE_FILE

logger = logging.getLogger(__name__)

# Keep arXiv IDs for FETCH_HOURS + 24h buffer to cover timing edge cases
_RETENTION_HOURS = FETCH_HOURS + 24

_DEFAULT_STATE: dict[str, Any] = {
    "notified_ids": {},
    "notified_blog_urls": {},
    "blog_arxiv_map": {},
    "daily_buffer": {},
}

_EMPTY_DAY: dict[str, list[Any]] = {
    "blog_posts": [],
    "arxiv_papers": [],
    "linked_papers": [],
    "safety_posts": [],
}


def _today_jst() -> str:
    """Return today's date in JST as YYYY-MM-DD."""
    return datetime.now(JST).strftime("%Y-%m-%d")


def _ensure_buffer_day(state: dict[str, Any], date_key: str) -> None:
    """Ensure the daily_buffer has an entry for the given date."""
    buf = state.setdefault("daily_buffer", {})
    if date_key not in buf:
        buf[date_key] = {k: list(v) for k, v in _EMPTY_DAY.items()}


def load_state() -> dict[str, Any]:
    """Load the state file. Returns default structure if missing or corrupt."""
    if not os.path.exists(STATE_FILE):
        return {k: (dict(v) if isinstance(v, dict) else v) for k, v in _DEFAULT_STATE.items()}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Corrupt state.json, starting fresh: %s", exc)
        return {k: (dict(v) if isinstance(v, dict) else v) for k, v in _DEFAULT_STATE.items()}
    # Migrate from old list format to dict format
    ids = data.get("notified_ids", {})
    if isinstance(ids, list):
        now = datetime.now(timezone.utc).isoformat()
        data["notified_ids"] = {aid: now for aid in ids}
    # Ensure all keys exist for forward compatibility
    for key, default in _DEFAULT_STATE.items():
        if key not in data:
            data[key] = dict(default) if isinstance(default, dict) else default
    return data


def save_state(state: dict[str, Any]) -> None:
    """Save state back to the JSON file."""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _prune_old_ids(state: dict[str, Any]) -> None:
    """Remove IDs, blog entries, and buffer days older than retention windows."""
    # Prune arXiv notified IDs
    arxiv_cutoff = datetime.now(timezone.utc) - timedelta(hours=_RETENTION_HOURS)
    ids = state.get("notified_ids", {})
    state["notified_ids"] = {
        aid: ts for aid, ts in ids.items()
        if ts > arxiv_cutoff.isoformat()
    }

    # Prune blog-related entries (30-day retention)
    blog_cutoff = datetime.now(timezone.utc) - timedelta(days=BLOG_RETENTION_DAYS)
    blog_cutoff_iso = blog_cutoff.isoformat()

    blog_urls = state.get("notified_blog_urls", {})
    state["notified_blog_urls"] = {
        url: ts for url, ts in blog_urls.items()
        if ts > blog_cutoff_iso
    }

    arxiv_map = state.get("blog_arxiv_map", {})
    state["blog_arxiv_map"] = {
        aid: info for aid, info in arxiv_map.items()
        if info.get("added_at", "") > blog_cutoff_iso
    }

    # Prune old daily buffer entries
    _prune_buffer(state)


def _prune_buffer(state: dict[str, Any]) -> None:
    """Remove daily_buffer entries older than BUFFER_RETENTION_DAYS."""
    buf = state.get("daily_buffer", {})
    cutoff = (datetime.now(JST) - timedelta(days=BUFFER_RETENTION_DAYS)).strftime("%Y-%m-%d")
    state["daily_buffer"] = {
        date_key: day for date_key, day in buf.items()
        if date_key >= cutoff
    }


# --- arXiv paper state ---

def filter_new_papers(
    papers: list[dict[str, Any]], state: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return only papers whose arXiv ID is not in the notified set."""
    seen = set(state.get("notified_ids", {}).keys())
    return [p for p in papers if p["arxiv_id"] not in seen]


def mark_notified(state: dict[str, Any], arxiv_ids: list[str]) -> None:
    """Add arXiv IDs to the notified set with current timestamp, then prune."""
    now = datetime.now(timezone.utc).isoformat()
    ids = state.get("notified_ids", {})
    for aid in arxiv_ids:
        ids[aid] = now
    state["notified_ids"] = ids
    _prune_old_ids(state)


# --- Blog state ---

def filter_new_blog_posts(
    posts: list[dict[str, Any]], state: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return only blog posts whose URL is not in the notified set."""
    seen = set(state.get("notified_blog_urls", {}).keys())
    return [p for p in posts if p["url"] not in seen]


def mark_blog_notified(
    state: dict[str, Any],
    posts: list[dict[str, Any]],
) -> None:
    """Record blog URLs as notified and save arXiv ID mappings from posts."""
    now = datetime.now(timezone.utc).isoformat()
    blog_urls = state.setdefault("notified_blog_urls", {})
    arxiv_map = state.setdefault("blog_arxiv_map", {})

    for post in posts:
        blog_urls[post["url"]] = now
        for aid in post.get("arxiv_ids", []):
            arxiv_map[aid] = {
                "blog_url": post["url"],
                "blog_title": post.get("title", ""),
                "blog_source": post.get("source", ""),
                "added_at": now,
            }


def lookup_blog_for_arxiv(
    state: dict[str, Any], arxiv_id: str
) -> dict[str, Any] | None:
    """Return blog info dict if an arXiv ID is linked to a blog post."""
    return state.get("blog_arxiv_map", {}).get(arxiv_id)


def mark_blog_arxiv_linked(state: dict[str, Any], arxiv_id: str) -> None:
    """Remove the arXiv→blog mapping after a linked notification is sent."""
    state.get("blog_arxiv_map", {}).pop(arxiv_id, None)


# --- Daily buffer (collect → briefing pipeline) ---

def buffer_blog_posts(state: dict[str, Any], posts: list[dict[str, Any]]) -> None:
    """Append blog posts to today's daily buffer, deduplicating by URL."""
    today = _today_jst()
    _ensure_buffer_day(state, today)
    existing = {p["url"] for p in state["daily_buffer"][today]["blog_posts"]}
    for post in posts:
        if post["url"] not in existing:
            state["daily_buffer"][today]["blog_posts"].append(post)
            existing.add(post["url"])


def buffer_safety_posts(state: dict[str, Any], posts: list[dict[str, Any]]) -> None:
    """Append safety blog posts to today's daily buffer, deduplicating by URL."""
    today = _today_jst()
    _ensure_buffer_day(state, today)
    existing = {p["url"] for p in state["daily_buffer"][today]["safety_posts"]}
    for post in posts:
        if post["url"] not in existing:
            state["daily_buffer"][today]["safety_posts"].append(post)
            existing.add(post["url"])


def buffer_arxiv_papers(state: dict[str, Any], papers: list[dict[str, Any]]) -> None:
    """Append keyword-matched arXiv papers to today's buffer, deduplicating by ID."""
    today = _today_jst()
    _ensure_buffer_day(state, today)
    existing = {p["arxiv_id"] for p in state["daily_buffer"][today]["arxiv_papers"]}
    for paper in papers:
        if paper["arxiv_id"] not in existing:
            state["daily_buffer"][today]["arxiv_papers"].append(paper)
            existing.add(paper["arxiv_id"])


def buffer_linked_papers(
    state: dict[str, Any],
    items: list[dict[str, Any]],
) -> None:
    """Append blog-linked arXiv papers to today's buffer, deduplicating by ID.

    Each item should have keys: "paper" (arXiv paper dict) and "blog_info" (blog info dict).
    """
    today = _today_jst()
    _ensure_buffer_day(state, today)
    existing = {
        it["paper"]["arxiv_id"]
        for it in state["daily_buffer"][today]["linked_papers"]
    }
    for item in items:
        aid = item["paper"]["arxiv_id"]
        if aid not in existing:
            state["daily_buffer"][today]["linked_papers"].append(item)
            existing.add(aid)


def peek_buffer(state: dict[str, Any]) -> dict[str, list[Any]]:
    """Aggregate all buffered items across all dates WITHOUT clearing the buffer.

    Returns dict with keys: blog_posts, arxiv_papers, linked_papers.
    """
    buf = state.get("daily_buffer", {})
    all_blog: list[dict[str, Any]] = []
    all_arxiv: list[dict[str, Any]] = []
    all_linked: list[dict[str, Any]] = []
    all_safety: list[dict[str, Any]] = []

    for date_key in sorted(buf.keys()):
        day = buf[date_key]
        all_blog.extend(day.get("blog_posts", []))
        all_arxiv.extend(day.get("arxiv_papers", []))
        all_linked.extend(day.get("linked_papers", []))
        all_safety.extend(day.get("safety_posts", []))

    return {
        "blog_posts": all_blog,
        "arxiv_papers": all_arxiv,
        "linked_papers": all_linked,
        "safety_posts": all_safety,
    }


def ack_buffer(state: dict[str, Any]) -> None:
    """Clear the daily buffer after a successful briefing send."""
    state["daily_buffer"] = {}
