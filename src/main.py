"""Main entry point for arXiv + tech blog Slack notifier.

Supports two execution modes controlled by the MODE environment variable:
  MODE=collect  — Fetch blogs & arXiv, buffer items to state. No Slack posting.
  MODE=brief    — Consume buffered items, build daily briefing, post to Slack.
"""

from __future__ import annotations

import logging
import os
import sys

# Ensure src/ is on the import path when run as a script
sys.path.insert(0, os.path.dirname(__file__))

from arxiv_client import fetch_recent_papers
from blog_client import fetch_blog_posts, fetch_safety_posts
from config import OUT_DIR
from slack import (
    build_daily_briefing_blocks,
    generate_briefing_markdown,
    generate_briefing_pdf,
    send_daily_briefing,
    upload_file,
)
from state import (
    ack_buffer,
    buffer_arxiv_papers,
    buffer_blog_posts,
    buffer_linked_papers,
    buffer_safety_posts,
    filter_new_blog_posts,
    filter_new_papers,
    load_state,
    lookup_blog_for_arxiv,
    mark_blog_arxiv_linked,
    mark_blog_notified,
    mark_notified,
    peek_buffer,
    save_state,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def run_collect() -> None:
    """Collect mode: fetch blogs & arXiv, buffer items, save state. No Slack."""
    state = load_state()

    # --- Blog RSS ---
    logger.info("Fetching blog RSS feeds...")
    blog_posts = fetch_blog_posts()
    logger.info("Found %d recent blog posts.", len(blog_posts))

    new_blog_posts = filter_new_blog_posts(blog_posts, state)
    logger.info("%d new blog posts to buffer.", len(new_blog_posts))

    if new_blog_posts:
        mark_blog_notified(state, new_blog_posts)
        buffer_blog_posts(state, new_blog_posts)
        total_arxiv_from_blogs = sum(len(p.get("arxiv_ids", [])) for p in new_blog_posts)
        logger.info("Saved %d arXiv ID mappings from blog posts.", total_arxiv_from_blogs)

    # --- Safety RSS ---
    logger.info("Fetching safety RSS feeds...")
    safety_posts = fetch_safety_posts()
    logger.info("Found %d recent safety posts.", len(safety_posts))

    new_safety_posts = filter_new_blog_posts(safety_posts, state)
    logger.info("%d new safety posts to buffer.", len(new_safety_posts))

    if new_safety_posts:
        mark_blog_notified(state, new_safety_posts)
        buffer_safety_posts(state, new_safety_posts)
        total_arxiv_from_safety = sum(len(p.get("arxiv_ids", [])) for p in new_safety_posts)
        logger.info("Saved %d arXiv ID mappings from safety posts.", total_arxiv_from_safety)

    # --- arXiv ---
    arxiv_ok = True
    try:
        logger.info("Fetching recent papers from arXiv...")
        papers = fetch_recent_papers()
        logger.info("Found %d matching papers in the last 48 hours.", len(papers))

        new_papers = filter_new_papers(papers, state)
        logger.info("%d new papers to buffer.", len(new_papers))

        linked_items: list[dict] = []
        keyword_papers: list[dict] = []

        for paper in new_papers:
            blog_info = lookup_blog_for_arxiv(state, paper["arxiv_id"])
            if blog_info:
                linked_items.append({"paper": paper, "blog_info": blog_info})
                mark_blog_arxiv_linked(state, paper["arxiv_id"])
            else:
                keyword_papers.append(paper)

        if linked_items:
            buffer_linked_papers(state, linked_items)
            logger.info("Buffered %d blog-linked papers.", len(linked_items))

        if keyword_papers:
            buffer_arxiv_papers(state, keyword_papers)
            logger.info("Buffered %d keyword-matched papers.", len(keyword_papers))

        # Mark arXiv IDs as notified (dedup for future collect runs) and prune
        all_ids = [p["arxiv_id"] for p in new_papers]
        if all_ids:
            mark_notified(state, all_ids)
    except Exception:
        arxiv_ok = False
        logger.warning(
            "arXiv fetch failed; blog data will still be saved. "
            "arXiv papers will be retried on next collect run.",
            exc_info=True,
        )

    save_state(state)
    if arxiv_ok:
        logger.info("Collect done. State saved.")
    else:
        logger.info("Collect done (arXiv skipped). Blog data saved.")


def run_brief() -> None:
    """Brief mode: peek buffer, build & send daily briefing, ack on success.

    Flow: peek → send (chat.postMessage) → generate md/pdf → upload → ack.
    Buffer data is preserved if any step before ack fails.
    """
    from datetime import datetime

    state = load_state()

    # Phase 1: peek — read without clearing
    items = peek_buffer(state)
    total = (
        len(items["blog_posts"])
        + len(items["arxiv_papers"])
        + len(items["linked_papers"])
        + len(items["safety_posts"])
    )

    logger.info(
        "Building briefing: %d blogs, %d arXiv, %d linked, %d safety.",
        len(items["blog_posts"]),
        len(items["arxiv_papers"]),
        len(items["linked_papers"]),
        len(items["safety_posts"]),
    )

    # Phase 2: send — raises on failure, buffer untouched
    blocks = build_daily_briefing_blocks(items)
    ts = send_daily_briefing(blocks)
    logger.info("Daily briefing sent to Slack (ts=%s).", ts)

    # Phase 3: generate Markdown / PDF and upload as thread replies
    OUT_DIR.mkdir(exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    md_path = OUT_DIR / f"briefing-{date_str}.md"
    pdf_path = OUT_DIR / f"briefing-{date_str}.pdf"

    md_content = generate_briefing_markdown(items)
    md_path.write_text(md_content, encoding="utf-8")
    logger.info("Markdown briefing written to %s.", md_path)

    upload_file(md_path, f"briefing-{date_str}.md", thread_ts=ts)
    logger.info("Markdown uploaded to Slack thread.")

    if generate_briefing_pdf(items, pdf_path):
        upload_file(pdf_path, f"briefing-{date_str}.pdf", thread_ts=ts)
        logger.info("PDF uploaded to Slack thread.")
    else:
        logger.warning("PDF generation failed; skipping PDF upload.")

    # Phase 4: ack — clear buffer only after confirmed send + upload
    ack_buffer(state)
    save_state(state)
    logger.info("Brief done. State saved.")


def main() -> None:
    mode = os.environ.get("MODE", "collect")
    logger.info("Running in mode: %s", mode)

    if mode == "collect":
        run_collect()
    elif mode == "brief":
        run_brief()
    else:
        raise ValueError(
            f"Unknown MODE='{mode}'. Expected 'collect' or 'brief'."
        )


if __name__ == "__main__":
    main()
