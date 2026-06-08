"""
Pipeline Orchestrator — run_pipeline.py

Ties all 6 stages together in sequence:
  1. Extract + Clean     → list[CleanedTweet]
  2. LLM Enrichment      → list[EnrichedTweet]  (+ cache)
  3. (cache is inline with Stage 2)
  4. Embedding Generation → embeddings attached
  5. Brand Normalization  → canonical names attached
  6. Load to SQLite       → corpus.db

Usage:
    python -m pipeline.run_pipeline
    python -m pipeline.run_pipeline --limit 50
    python -m pipeline.run_pipeline --skip-llm
    python -m pipeline.run_pipeline --skip-embeddings
    python -m pipeline.run_pipeline --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Load environment variables (.env) if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Pipeline stages
from .extract_clean import extract_and_clean
from .llm_enrich import enrich_tweets
from .generate_embeddings import generate_embeddings
from .brand_normalize import normalize_brands
from .load_db import load_all

logger = logging.getLogger(__name__)

WORKSPACE = Path(__file__).resolve().parent.parent



def main():
    parser = argparse.ArgumentParser(
        description="Hairfall Insights ETL Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m pipeline.run_pipeline --limit 5          # Test with 5 tweets
  python -m pipeline.run_pipeline --skip-llm         # Re-process from cache
  python -m pipeline.run_pipeline --skip-embeddings   # Skip embedding step
  python -m pipeline.run_pipeline --dry-run           # Don't write to DB
        """,
    )
    parser.add_argument(
        "--input",
        type=str,
        default=str(WORKSPACE / "data" / "processed" / "fix_data.csv"),
        help="Input CSV path (default: data/processed/fix_data.csv)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only first N tweets (for testing)",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Skip the first N tweets in the input CSV",
    )
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="Skip LLM calls, read from cache only",
    )
    parser.add_argument(
        "--skip-embeddings",
        action="store_true",
        help="Skip embedding generation",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run stages 1-5 but don't write to DB",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=str(WORKSPACE / "pipeline_output" / "corpus.db"),
        help="Output database path",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    # Set up logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    start_time = time.time()

    print("=" * 60)
    print("  Hairfall Insights — ETL Pipeline")
    print("=" * 60)

    # -----------------------------------------------------------------------
    # Stage 1: Extract + Clean
    # -----------------------------------------------------------------------
    print("\n▶ Stage 1: Extract + Clean")
    tweets = extract_and_clean(input_path=args.input, limit=args.limit, offset=args.offset)
    non_spam = [t for t in tweets if not t.is_spam]
    print(f"  ✓ {len(tweets)} tweets extracted ({len(tweets) - len(non_spam)} spam flagged)")

    if not tweets:
        print("  ✗ No tweets to process. Exiting.")
        sys.exit(1)

    # -----------------------------------------------------------------------
    # Stage 2+3: LLM Enrichment + Cache
    # -----------------------------------------------------------------------
    print("\n▶ Stage 2: LLM Enrichment" + (" (cache-only mode)" if args.skip_llm else ""))
    enriched, dead_count = enrich_tweets(
        tweets,
        cache_path=WORKSPACE / "pipeline_output" / "llm_cache.json",
        dead_letter_path=WORKSPACE / "pipeline_output" / "dead_letter.json",
        skip_llm=args.skip_llm,
    )
    print(f"  ✓ {len(enriched)} enriched, {dead_count} dead-lettered")

    if not enriched:
        print("  ✗ No enriched tweets. Check dead_letter.json for errors.")
        if args.skip_llm:
            print("  ℹ  Hint: Remove --skip-llm to make API calls")
        sys.exit(1)

    # -----------------------------------------------------------------------
    # Stage 4: Embeddings
    # -----------------------------------------------------------------------
    if not args.skip_embeddings:
        print("\n▶ Stage 4: Embedding Generation")
        enriched = generate_embeddings(enriched)
        embedded_count = sum(1 for t in enriched if t.embedding is not None)
        print(f"  ✓ {embedded_count} embeddings generated")
    else:
        print("\n▶ Stage 4: Skipped (--skip-embeddings)")

    # -----------------------------------------------------------------------
    # Stage 5: Brand Normalization
    # -----------------------------------------------------------------------
    print("\n▶ Stage 5: Brand Normalization")
    enriched = normalize_brands(
        enriched,
        lookup_path=WORKSPACE / "config" / "lookup_tables" / "brand_canonical.json",
    )
    brand_count = sum(len(t.brands_raw) for t in enriched)
    print(f"  ✓ {brand_count} brand mentions processed")

    # -----------------------------------------------------------------------
    # Stage 6: Load to DB
    # -----------------------------------------------------------------------
    if not args.dry_run:
        print(f"\n▶ Stage 6: Loading to {args.db_path}")
        load_all(enriched, db_path=args.db_path)
        print(f"  ✓ {len(enriched)} tweets loaded into corpus.db")
    else:
        print(f"\n▶ Stage 6: Skipped (--dry-run)")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    elapsed = time.time() - start_time
    print("\n" + "=" * 60)
    print(f"  Pipeline complete in {elapsed:.1f}s")
    print(f"  Tweets processed:  {len(enriched)}")
    print(f"  Dead-lettered:     {dead_count}")
    if not args.dry_run:
        print(f"  Database:          {args.db_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
