"""
Stage 1 — Extract + Clean

Reads fix_data.csv and produces a list[CleanedTweet] in memory.
Pure preprocessing — no LLM, no DB writes, fully stateless.
"""

from __future__ import annotations

import ast
import csv
import json
import logging
import re
from pathlib import Path
from typing import Optional

from .schema import CleanedTweet

logger = logging.getLogger(__name__)

# Default input path
DEFAULT_INPUT = Path(__file__).resolve().parent.parent / "data" / "processed" / "fix_data.csv"


# ---------------------------------------------------------------------------
# Helpers — reusing patterns from script/merge_and_clean.py
# ---------------------------------------------------------------------------

def _parse_dict_string(s: str) -> dict:
    """Parse a Python dict literal or JSON string."""
    if not s:
        return {}
    try:
        return ast.literal_eval(s)
    except Exception:
        try:
            return json.loads(s)
        except Exception:
            return {}


def _safe_int(val) -> int:
    if not val:
        return 0
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return 0


def _extract_from_raw(raw_str: str) -> dict:
    """
    Extract metadata fields from the nested `raw` JSON column.

    Handles both standard `Tweet` and `TweetWithVisibilityResults` structures.
    Returns a dict with: view_count, source, lang, user_location, followers_count.
    """
    raw = _parse_dict_string(raw_str)
    if not raw:
        return {}

    # Unwrap TweetWithVisibilityResults
    if raw.get("__typename") == "TweetWithVisibilityResults":
        raw = raw.get("tweet", {})

    result = {}

    # View count from legacy extended stats
    legacy = raw.get("legacy", {})
    ext_views = raw.get("views", {})
    if ext_views:
        result["view_count"] = _safe_int(ext_views.get("count", 0))

    # Source app (e.g., "Twitter for iPhone")
    source_html = raw.get("source", "")
    if source_html:
        # Source comes as HTML like '<a href="...">Twitter for iPhone</a>'
        match = re.search(r">(.+?)<", source_html)
        result["source"] = match.group(1) if match else source_html

    # Language
    if legacy.get("lang"):
        result["lang"] = legacy["lang"]

    # User location and followers from core.user_results
    user_results = raw.get("core", {}).get("user_results", {}).get("result", {})
    if user_results:
        user_legacy = user_results.get("legacy", {})
        if user_legacy:
            result["user_location"] = user_legacy.get("location", "")
            result["followers_count"] = _safe_int(user_legacy.get("followers_count", 0))

    return result


# ---------------------------------------------------------------------------
# Text Normalization
# ---------------------------------------------------------------------------

# Compiled regexes for performance
_URL_PATTERN = re.compile(r"https?://\S+")
_MENTION_PATTERN = re.compile(r"@\w+")
_MULTI_SPACE = re.compile(r"\s+")


def _normalize_text(text: str) -> str:
    """
    Clean tweet text:
    - Strip URLs
    - Strip @mentions
    - Collapse whitespace
    - Strip leading/trailing whitespace
    """
    if not text:
        return ""
    text = _URL_PATTERN.sub("", text)
    text = _MENTION_PATTERN.sub("", text)
    text = _MULTI_SPACE.sub(" ", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Spam Detection (Heuristic)
# ---------------------------------------------------------------------------

def _is_spam(text: str, raw_text: str) -> bool:
    """
    Simple spam heuristics:
    - Cleaned text is < 10 characters
    - Original text is mostly URLs (>50% of content)
    """
    if len(text) < 10:
        return True

    # Count URL characters vs total
    urls = _URL_PATTERN.findall(raw_text)
    url_chars = sum(len(u) for u in urls)
    if raw_text and url_chars / max(len(raw_text), 1) > 0.5:
        return True

    return False


# ---------------------------------------------------------------------------
# Main extraction function
# ---------------------------------------------------------------------------

def extract_and_clean(
    input_path: Optional[str | Path] = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> list[CleanedTweet]:
    """
    Stage 1: Read CSV, normalize, and return clean tweet objects.

    Args:
        input_path: Path to the CSV file. Defaults to Data/processed/fix_data.csv.
        limit: If set, only process this many rows (for testing).
        offset: Skip the first N rows.

    Returns:
        List of CleanedTweet objects, ready for LLM enrichment.
    """
    path = Path(input_path) if input_path else DEFAULT_INPUT
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    tweets: list[CleanedTweet] = []
    skipped = 0
    spam_count = 0

    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if offset and i < offset:
                continue
            if limit and len(tweets) >= limit:
                break

            tweet_id = (row.get("tweet_id") or "").strip()
            raw_text = row.get("text", "") or row.get("embedded_text", "") or ""

            # Skip rows without tweet_id or text
            if not tweet_id or not raw_text.strip():
                skipped += 1
                continue

            # Normalize text
            clean_text = _normalize_text(raw_text)
            if not clean_text:
                skipped += 1
                continue

            # Extract metadata from raw JSON
            raw_meta = _extract_from_raw(row.get("raw", ""))

            # Determine spam
            spam = _is_spam(clean_text, raw_text)
            if spam:
                spam_count += 1

            # Build screen_name from available fields
            screen_name = (
                row.get("user_screen_name")
                or row.get("user_username")
                or ""
            ).strip()

            # Parse timestamp
            created_at = (row.get("timestamp") or "").strip()

            try:
                tweet = CleanedTweet(
                    tweet_id=tweet_id,
                    full_text=clean_text,
                    screen_name=screen_name,
                    followers_count=raw_meta.get("followers_count", _safe_int(row.get("user_followers"))),
                    created_at=created_at,
                    lang=raw_meta.get("lang", ""),
                    source=raw_meta.get("source", ""),
                    retweet_count=_safe_int(row.get("retweets")),
                    like_count=_safe_int(row.get("likes")),
                    reply_count=_safe_int(row.get("comments")),
                    view_count=raw_meta.get("view_count", 0),
                    user_location=raw_meta.get("user_location", ""),
                    is_spam=spam,
                )
                tweets.append(tweet)
            except Exception as e:
                logger.warning(f"Row {i} failed validation: {e}")
                skipped += 1

    logger.info(
        f"Stage 1 complete: {len(tweets)} tweets extracted, "
        f"{skipped} skipped, {spam_count} flagged as spam"
    )
    return tweets


# ---------------------------------------------------------------------------
# CLI entry point for standalone testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Stage 1: Extract + Clean")
    parser.add_argument("--input", type=str, default=None, help="Input CSV path")
    parser.add_argument("--limit", type=int, default=None, help="Max rows to process")
    parser.add_argument("--offset", type=int, default=0, help="Skip the first N rows")
    args = parser.parse_args()

    tweets = extract_and_clean(input_path=args.input, limit=args.limit, offset=args.offset)

    print(f"\nExtracted {len(tweets)} tweets")
    spam = sum(1 for t in tweets if t.is_spam)
    print(f"Spam flagged: {spam}")

    if tweets:
        print(f"\nSample tweet:")
        sample = tweets[0]
        print(f"  ID:     {sample.tweet_id}")
        print(f"  Text:   {sample.full_text[:100]}...")
        print(f"  User:   {sample.screen_name}")
        print(f"  Lang:   {sample.lang}")
        print(f"  Source:  {sample.source}")
        print(f"  Likes:  {sample.like_count}")
        print(f"  Views:  {sample.view_count}")
        print(f"  Spam:   {sample.is_spam}")
