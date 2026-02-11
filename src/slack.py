"""Send Slack notifications via Bot Token (Web API) and generate Markdown/PDF briefings."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from xhtml2pdf import pisa

from config import (
    ARXIV_CATEGORIES,
    FETCH_HOURS,
    JST,
    OUT_DIR,
    SLACK_BOT_TOKEN,
    SLACK_CHANNEL_ID,
)

# Max items shown per briefing section
_MAX_ITEMS_PER_SECTION = 5

# Summary preview length in briefing items
_SUMMARY_PREVIEW_LEN = 150


def _truncate(text: str, limit: int) -> str:
    """Truncate text and append ellipsis if it exceeds the limit."""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "\u2026"


def _slack_api(
    method: str,
    *,
    json_data: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call a Slack Web API method and return the parsed JSON response.

    Raises ``RuntimeError`` on API-level errors (``ok: false``).
    Token values are never included in error messages.
    """
    if not SLACK_BOT_TOKEN:
        raise RuntimeError(
            "SLACK_BOT_TOKEN is not set. "
            "Export it as an environment variable before running."
        )

    url = f"https://slack.com/api/{method}"
    headers: dict[str, str] = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}

    if files is not None:
        # multipart/form-data — do NOT set Content-Type; requests handles it
        resp = requests.post(url, headers=headers, data=data, files=files, timeout=60)
    elif data is not None:
        # application/x-www-form-urlencoded (required by some methods)
        resp = requests.post(url, headers=headers, data=data, timeout=30)
    else:
        headers["Content-Type"] = "application/json; charset=utf-8"
        resp = requests.post(url, headers=headers, json=json_data, timeout=30)

    resp.raise_for_status()
    body = resp.json()

    if not body.get("ok"):
        error = body.get("error", "unknown_error")
        raise RuntimeError(f"Slack API {method} failed: {error}")

    return body


# ---------------------------------------------------------------------------
# Daily Briefing builder
# ---------------------------------------------------------------------------

def _build_blog_item(post: dict[str, Any]) -> str:
    """Format a single blog post as mrkdwn text."""
    title = post.get("title", "No title")
    url = post.get("url", "")
    source = post.get("source", "Blog")
    published = post.get("published", "")[:10]  # YYYY-MM-DD

    line = f"*<{url}|{title}>*\n_{source}_ \u00b7 {published}"

    arxiv_ids = post.get("arxiv_ids", [])
    if arxiv_ids:
        links = ", ".join(f"<https://arxiv.org/abs/{aid}|{aid}>" for aid in arxiv_ids[:3])
        line += f" \u00b7 arXiv: {links}"

    summary = post.get("summary", "")
    if summary:
        line += f"\n{_truncate(summary, _SUMMARY_PREVIEW_LEN)}"

    return line


def _build_arxiv_item(paper: dict[str, Any]) -> str:
    """Format a single arXiv paper as mrkdwn text."""
    title = paper.get("title", "No title")
    arxiv_id = paper.get("arxiv_id", "unknown")
    link = paper.get("link", f"https://arxiv.org/abs/{arxiv_id}")
    keywords = ", ".join(paper.get("matched_keywords", []))

    line = f"*<{link}|{title}>*\n`{arxiv_id}` \u00b7 {keywords}"

    summary = paper.get("summary", "")
    if summary:
        line += f"\n{_truncate(summary, _SUMMARY_PREVIEW_LEN)}"

    return line


def _build_linked_item(item: dict[str, Any]) -> str:
    """Format a blog-linked arXiv paper as mrkdwn text."""
    paper = item.get("paper", {})
    blog_info = item.get("blog_info", {})

    title = paper.get("title", "No title")
    arxiv_id = paper.get("arxiv_id", "unknown")
    link = paper.get("link", f"https://arxiv.org/abs/{arxiv_id}")
    blog_source = blog_info.get("blog_source", "Blog")
    blog_title = blog_info.get("blog_title", "")
    blog_url = blog_info.get("blog_url", "")

    blog_ref = f"<{blog_url}|{blog_title}>" if blog_url and blog_title else blog_source

    line = f"*<{link}|{title}>*\n`{arxiv_id}` \u00b7 {blog_ref} ({blog_source})"

    summary = paper.get("summary", "")
    if summary:
        line += f"\n{_truncate(summary, _SUMMARY_PREVIEW_LEN)}"

    return line


def build_daily_briefing_blocks(items: dict[str, list[Any]]) -> list[dict[str, Any]]:
    """Build Block Kit blocks for the daily briefing message.

    Args:
        items: dict with keys blog_posts, arxiv_papers, linked_papers.

    Returns:
        List of Slack Block Kit block dicts.
    """
    date_str = datetime.now(JST).strftime("%Y-%m-%d")
    blog_posts = items.get("blog_posts", [])
    arxiv_papers = items.get("arxiv_papers", [])
    linked_papers = items.get("linked_papers", [])

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"Daily AI Research Briefing \u2014 {date_str} (JST)",
                "emoji": False,
            },
        },
    ]

    # --- Section A: High Priority (blog posts) ---
    if blog_posts:
        blocks.append({"type": "divider"})
        shown = blog_posts[:_MAX_ITEMS_PER_SECTION]
        overflow = len(blog_posts) - len(shown)
        header = f":fire:  *High Priority \u2014 Tech Blog Posts*  ({len(blog_posts)})"
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": header},
        })
        for post in shown:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": _build_blog_item(post)},
            })
        if overflow > 0:
            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"_+{overflow} more blog posts_"}],
            })

    # --- Section B: Notable arXiv (keyword-matched) ---
    if arxiv_papers:
        blocks.append({"type": "divider"})
        shown = arxiv_papers[:_MAX_ITEMS_PER_SECTION]
        overflow = len(arxiv_papers) - len(shown)
        header = f":test_tube:  *Notable arXiv Papers*  ({len(arxiv_papers)})"
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": header},
        })
        for paper in shown:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": _build_arxiv_item(paper)},
            })
        if overflow > 0:
            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"_+{overflow} more arXiv papers_"}],
            })

    # --- Section C: Blog ↔ arXiv Updates (linked) ---
    if linked_papers:
        blocks.append({"type": "divider"})
        shown = linked_papers[:_MAX_ITEMS_PER_SECTION]
        overflow = len(linked_papers) - len(shown)
        header = f":link:  *Blog \u2194 arXiv Updates*  ({len(linked_papers)})"
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": header},
        })
        for item in shown:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": _build_linked_item(item)},
            })
        if overflow > 0:
            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"_+{overflow} more linked papers_"}],
            })

    # --- Footer ---
    total = len(blog_posts) + len(arxiv_papers) + len(linked_papers)
    cats = ", ".join(ARXIV_CATEGORIES)
    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": (
                    f":bar_chart:  {cats} \u00b7 Past {FETCH_HOURS}h \u00b7 "
                    f"{len(blog_posts)} blogs, {len(arxiv_papers)} arXiv, "
                    f"{len(linked_papers)} linked \u00b7 {total} total"
                ),
            },
        ],
    })

    return blocks


def send_daily_briefing(blocks: list[dict[str, Any]]) -> str:
    """Send the daily briefing to Slack via chat.postMessage.

    Returns the message ``ts`` (timestamp) for threading follow-up uploads.
    """
    if not SLACK_CHANNEL_ID:
        raise RuntimeError(
            "SLACK_CHANNEL_ID is not set. "
            "Export it as an environment variable before running."
        )

    date_str = datetime.now(JST).strftime("%Y-%m-%d")
    body = _slack_api("chat.postMessage", json_data={
        "channel": SLACK_CHANNEL_ID,
        "text": f"Daily AI Research Briefing \u2014 {date_str}",
        "blocks": blocks,
    })
    return body["ts"]


def upload_file(file_path: Path, title: str, thread_ts: str | None = None) -> None:
    """Upload a file to Slack using the v2 upload flow, optionally as a thread reply.

    Steps:
      1. files.getUploadURLExternal → obtain upload_url and file_id
      2. POST file content to the upload_url
      3. files.completeUploadExternal → share file to channel/thread
    """
    if not SLACK_CHANNEL_ID:
        raise RuntimeError(
            "SLACK_CHANNEL_ID is not set. "
            "Export it as an environment variable before running."
        )

    file_size = file_path.stat().st_size

    # Step 1: get upload URL (form-encoded, not JSON)
    url_resp = _slack_api("files.getUploadURLExternal", data={
        "filename": file_path.name,
        "length": str(file_size),
    })
    upload_url = url_resp["upload_url"]
    file_id = url_resp["file_id"]

    # Step 2: upload file content to the presigned URL
    with open(file_path, "rb") as f:
        resp = requests.post(upload_url, data=f, timeout=60)
    resp.raise_for_status()

    # Step 3: complete upload and share to channel/thread
    complete_data: dict[str, Any] = {
        "files": [{"id": file_id, "title": title}],
        "channel_id": SLACK_CHANNEL_ID,
    }
    if thread_ts is not None:
        complete_data["thread_ts"] = thread_ts

    _slack_api("files.completeUploadExternal", json_data=complete_data)


# ---------------------------------------------------------------------------
# Markdown / PDF briefing generation
# ---------------------------------------------------------------------------

def generate_briefing_markdown(items: dict[str, list[Any]]) -> str:
    """Generate a Markdown document equivalent to the Block Kit briefing."""
    date_str = datetime.now(JST).strftime("%Y-%m-%d")
    blog_posts = items.get("blog_posts", [])
    arxiv_papers = items.get("arxiv_papers", [])
    linked_papers = items.get("linked_papers", [])

    lines: list[str] = []
    lines.append(f"# Daily AI Research Briefing \u2014 {date_str} (JST)")
    lines.append("")

    # --- Section A: High Priority ---
    if blog_posts:
        lines.append(f"## \U0001f525 High Priority \u2014 Tech Blog Posts ({len(blog_posts)})")
        lines.append("")
        for post in blog_posts[:_MAX_ITEMS_PER_SECTION]:
            title = post.get("title", "No title")
            url = post.get("url", "")
            source = post.get("source", "Blog")
            published = post.get("published", "")[:10]
            lines.append(f"- **[{title}]({url})**")
            lines.append(f"  {source} \u00b7 {published}")
            arxiv_ids = post.get("arxiv_ids", [])
            if arxiv_ids:
                links = ", ".join(
                    f"[{aid}](https://arxiv.org/abs/{aid})" for aid in arxiv_ids[:3]
                )
                lines.append(f"  arXiv: {links}")
            summary = post.get("summary", "")
            if summary:
                lines.append(f"  {_truncate(summary, _SUMMARY_PREVIEW_LEN)}")
            lines.append("")
        overflow = len(blog_posts) - _MAX_ITEMS_PER_SECTION
        if overflow > 0:
            lines.append(f"_+{overflow} more blog posts_")
            lines.append("")

    # --- Section B: Notable arXiv ---
    if arxiv_papers:
        lines.append(f"## \U0001f9ea Notable arXiv Papers ({len(arxiv_papers)})")
        lines.append("")
        for paper in arxiv_papers[:_MAX_ITEMS_PER_SECTION]:
            title = paper.get("title", "No title")
            arxiv_id = paper.get("arxiv_id", "unknown")
            link = paper.get("link", f"https://arxiv.org/abs/{arxiv_id}")
            pdf_link = f"https://arxiv.org/pdf/{arxiv_id}"
            keywords = ", ".join(paper.get("matched_keywords", []))
            lines.append(f"- **[{title}]({link})** ([PDF]({pdf_link}))")
            lines.append(f"  `{arxiv_id}` \u00b7 {keywords}")
            summary = paper.get("summary", "")
            if summary:
                lines.append(f"  {_truncate(summary, _SUMMARY_PREVIEW_LEN)}")
            lines.append("")
        overflow = len(arxiv_papers) - _MAX_ITEMS_PER_SECTION
        if overflow > 0:
            lines.append(f"_+{overflow} more arXiv papers_")
            lines.append("")

    # --- Section C: Blog ↔ arXiv Updates ---
    if linked_papers:
        lines.append(f"## \U0001f517 Blog \u2194 arXiv Updates ({len(linked_papers)})")
        lines.append("")
        for item in linked_papers[:_MAX_ITEMS_PER_SECTION]:
            paper = item.get("paper", {})
            blog_info = item.get("blog_info", {})
            title = paper.get("title", "No title")
            arxiv_id = paper.get("arxiv_id", "unknown")
            link = paper.get("link", f"https://arxiv.org/abs/{arxiv_id}")
            pdf_link = f"https://arxiv.org/pdf/{arxiv_id}"
            blog_source = blog_info.get("blog_source", "Blog")
            blog_title = blog_info.get("blog_title", "")
            blog_url = blog_info.get("blog_url", "")
            blog_ref = f"[{blog_title}]({blog_url})" if blog_url and blog_title else blog_source
            lines.append(f"- **[{title}]({link})** ([PDF]({pdf_link}))")
            lines.append(f"  `{arxiv_id}` \u00b7 {blog_ref} ({blog_source})")
            summary = paper.get("summary", "")
            if summary:
                lines.append(f"  {_truncate(summary, _SUMMARY_PREVIEW_LEN)}")
            lines.append("")
        overflow = len(linked_papers) - _MAX_ITEMS_PER_SECTION
        if overflow > 0:
            lines.append(f"_+{overflow} more linked papers_")
            lines.append("")

    # --- Footer ---
    total = len(blog_posts) + len(arxiv_papers) + len(linked_papers)
    cats = ", ".join(ARXIV_CATEGORIES)
    lines.append("---")
    lines.append("")
    lines.append(
        f"{cats} \u00b7 Past {FETCH_HOURS}h \u00b7 "
        f"{len(blog_posts)} blogs, {len(arxiv_papers)} arXiv, "
        f"{len(linked_papers)} linked \u00b7 {total} total"
    )
    lines.append("")

    return "\n".join(lines)


_PDF_CSS = """\
@page { size: A4; margin: 2cm 2.2cm; }
body { font-family: Helvetica, Arial, sans-serif; color: #222; font-size: 10px; line-height: 1.55; }
h1 { font-size: 18px; color: #0f3460; border-bottom: 2px solid #e94560; padding-bottom: 5px;
     margin: 0 0 14px 0; }
.section { margin-top: 16px; }
.section-head { font-size: 13px; font-weight: bold; color: #16213e;
                border-bottom: 1px solid #ddd; padding-bottom: 3px; margin-bottom: 8px; }
.card { background: #f9f9fb; border-left: 3px solid #1a73e8; padding: 6px 10px;
        margin-bottom: 8px; }
.card-title { font-size: 11px; font-weight: bold; margin: 0; }
.card-title a { color: #1a73e8; text-decoration: none; }
.card-meta { font-size: 9px; color: #555; margin: 2px 0 0 0; }
.card-meta a { color: #1a73e8; text-decoration: none; }
.card-meta .tag { background: #e8eaf6; padding: 0 4px; font-family: Courier; font-size: 8.5px; }
.card-summary { font-size: 9.5px; color: #444; margin: 3px 0 0 0; }
.overflow { font-size: 9px; color: #888; font-style: italic; margin: 2px 0 8px 0; }
.footer { border-top: 1px solid #ccc; margin-top: 18px; padding-top: 6px;
          font-size: 9px; color: #777; }
"""


def _html_escape(text: str) -> str:
    """Minimal HTML escaping for user-provided text."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _build_pdf_html(items: dict[str, list[Any]]) -> str:
    """Build styled HTML for PDF directly from briefing items."""
    date_str = datetime.now(JST).strftime("%Y-%m-%d")
    blog_posts = items.get("blog_posts", [])
    arxiv_papers = items.get("arxiv_papers", [])
    linked_papers = items.get("linked_papers", [])

    parts: list[str] = [
        '<!DOCTYPE html><html><head><meta charset="utf-8">',
        f"<style>{_PDF_CSS}</style></head><body>",
        f"<h1>Daily AI Research Briefing &mdash; {date_str} (JST)</h1>",
    ]

    # --- Section A: High Priority ---
    if blog_posts:
        parts.append('<div class="section">')
        parts.append(
            f'<div class="section-head">High Priority &mdash; Tech Blog Posts ({len(blog_posts)})</div>'
        )
        for post in blog_posts[:_MAX_ITEMS_PER_SECTION]:
            title = _html_escape(post.get("title", "No title"))
            url = post.get("url", "")
            source = _html_escape(post.get("source", "Blog"))
            published = post.get("published", "")[:10]
            arxiv_ids = post.get("arxiv_ids", [])
            summary = post.get("summary", "")

            parts.append('<div class="card">')
            parts.append(f'<p class="card-title"><a href="{url}">{title}</a></p>')
            meta = f"{source} &middot; {published}"
            if arxiv_ids:
                links = ", ".join(
                    f'<a href="https://arxiv.org/abs/{aid}">{aid}</a>'
                    for aid in arxiv_ids[:3]
                )
                meta += f" &middot; arXiv: {links}"
            parts.append(f'<p class="card-meta">{meta}</p>')
            if summary:
                parts.append(
                    f'<p class="card-summary">{_html_escape(_truncate(summary, _SUMMARY_PREVIEW_LEN))}</p>'
                )
            parts.append("</div>")

        overflow = len(blog_posts) - _MAX_ITEMS_PER_SECTION
        if overflow > 0:
            parts.append(f'<p class="overflow">+{overflow} more blog posts</p>')
        parts.append("</div>")

    # --- Section B: Notable arXiv ---
    if arxiv_papers:
        parts.append('<div class="section">')
        parts.append(
            f'<div class="section-head">Notable arXiv Papers ({len(arxiv_papers)})</div>'
        )
        for paper in arxiv_papers[:_MAX_ITEMS_PER_SECTION]:
            title = _html_escape(paper.get("title", "No title"))
            arxiv_id = paper.get("arxiv_id", "unknown")
            link = paper.get("link", f"https://arxiv.org/abs/{arxiv_id}")
            pdf_link = f"https://arxiv.org/pdf/{arxiv_id}"
            keywords = _html_escape(", ".join(paper.get("matched_keywords", [])))
            summary = paper.get("summary", "")

            parts.append('<div class="card">')
            parts.append(
                f'<p class="card-title"><a href="{link}">{title}</a>'
                f' &nbsp;<a href="{pdf_link}" style="font-size:9px;font-weight:normal;">[PDF]</a></p>'
            )
            parts.append(
                f'<p class="card-meta"><span class="tag">{arxiv_id}</span> &middot; {keywords}</p>'
            )
            if summary:
                parts.append(
                    f'<p class="card-summary">{_html_escape(_truncate(summary, _SUMMARY_PREVIEW_LEN))}</p>'
                )
            parts.append("</div>")

        overflow = len(arxiv_papers) - _MAX_ITEMS_PER_SECTION
        if overflow > 0:
            parts.append(f'<p class="overflow">+{overflow} more arXiv papers</p>')
        parts.append("</div>")

    # --- Section C: Blog <-> arXiv Updates ---
    if linked_papers:
        parts.append('<div class="section">')
        parts.append(
            f'<div class="section-head">Blog / arXiv Updates ({len(linked_papers)})</div>'
        )
        for item in linked_papers[:_MAX_ITEMS_PER_SECTION]:
            paper = item.get("paper", {})
            blog_info = item.get("blog_info", {})
            title = _html_escape(paper.get("title", "No title"))
            arxiv_id = paper.get("arxiv_id", "unknown")
            link = paper.get("link", f"https://arxiv.org/abs/{arxiv_id}")
            pdf_link = f"https://arxiv.org/pdf/{arxiv_id}"
            blog_source = _html_escape(blog_info.get("blog_source", "Blog"))
            blog_title = _html_escape(blog_info.get("blog_title", ""))
            blog_url = blog_info.get("blog_url", "")
            summary = paper.get("summary", "")

            blog_ref = (
                f'<a href="{blog_url}">{blog_title}</a>'
                if blog_url and blog_title
                else blog_source
            )

            parts.append('<div class="card">')
            parts.append(
                f'<p class="card-title"><a href="{link}">{title}</a>'
                f' &nbsp;<a href="{pdf_link}" style="font-size:9px;font-weight:normal;">[PDF]</a></p>'
            )
            parts.append(
                f'<p class="card-meta"><span class="tag">{arxiv_id}</span>'
                f" &middot; {blog_ref} ({blog_source})</p>"
            )
            if summary:
                parts.append(
                    f'<p class="card-summary">{_html_escape(_truncate(summary, _SUMMARY_PREVIEW_LEN))}</p>'
                )
            parts.append("</div>")

        overflow = len(linked_papers) - _MAX_ITEMS_PER_SECTION
        if overflow > 0:
            parts.append(f'<p class="overflow">+{overflow} more linked papers</p>')
        parts.append("</div>")

    # --- Footer ---
    total = len(blog_posts) + len(arxiv_papers) + len(linked_papers)
    cats = ", ".join(ARXIV_CATEGORIES)
    parts.append(
        f'<div class="footer">{cats} &middot; Past {FETCH_HOURS}h &middot; '
        f"{len(blog_posts)} blogs, {len(arxiv_papers)} arXiv, "
        f"{len(linked_papers)} linked &middot; {total} total</div>"
    )

    parts.append("</body></html>")
    return "\n".join(parts)


def generate_briefing_pdf(items: dict[str, list[Any]], pdf_path: Path) -> bool:
    """Generate a styled PDF briefing directly from items data.

    Returns ``True`` on success, ``False`` on conversion failure.
    """
    html = _build_pdf_html(items)
    with open(pdf_path, "wb") as f:
        status = pisa.CreatePDF(html, dest=f)
    return not status.err
