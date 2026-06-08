"""
Stage 3 — LLM Response Cache

Manages llm_cache.json: a tweet_id-keyed dictionary of raw LLM responses.
This enables zero-cost re-runs and provides an audit trail for debugging.

Cache format:
{
  "tweet_id_9001": {
    "response": { "intent": "complaining", "causes": [...], ... },
    "model": "deepseek-chat",
    "cached_at": "2026-05-26T10:00:00Z"
  }
}
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = Path(__file__).resolve().parent.parent / "pipeline_output" / "llm_cache.json"


def load_cache(path: str | Path | None = None) -> dict[str, dict]:
    """Load the cache from disk. Returns empty dict if file doesn't exist."""
    cache_path = Path(path) if path else DEFAULT_CACHE_PATH
    if not cache_path.exists():
        logger.info(f"No cache file found at {cache_path}, starting fresh")
        return {}

    with open(cache_path, "r", encoding="utf-8") as f:
        cache = json.load(f)

    logger.info(f"Loaded cache with {len(cache)} entries from {cache_path}")
    return cache


def save_cache(cache: dict[str, dict], path: str | Path | None = None) -> None:
    """Write the cache to disk atomically (write to tmp, then rename)."""
    cache_path = Path(path) if path else DEFAULT_CACHE_PATH
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = cache_path.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    tmp_path.rename(cache_path)
    logger.debug(f"Saved cache with {len(cache)} entries to {cache_path}")


def is_cached(cache: dict[str, dict], tweet_id: str) -> bool:
    """Check if a tweet_id has a cached response."""
    return tweet_id in cache


def get_cached(cache: dict[str, dict], tweet_id: str) -> dict | None:
    """Get the raw LLM response dict for a tweet, or None if not cached."""
    entry = cache.get(tweet_id)
    if entry is None:
        return None
    return entry.get("response")


def set_cached(
    cache: dict[str, dict],
    tweet_id: str,
    response: dict,
    model: str,
) -> None:
    """Add a new entry to the cache (in-memory). Call save_cache() to persist."""
    cache[tweet_id] = {
        "response": response,
        "model": model,
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
