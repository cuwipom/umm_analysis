"""
Stage 6 — Load Into Database

Writes enriched tweets to corpus.db (SQLite) with 6 normalized tables.
Idempotent: uses INSERT OR REPLACE + child table delete-reinsert pattern.

Why 6 tables instead of 1 (from Architecture.md):
One tweet can have multiple causes, brands, products, barriers, aspects.
Normalized tables enable clean SQL aggregation (GROUP BY, COUNT, JOIN).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from .schema import EnrichedTweet

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "pipeline_output" / "corpus.db"


# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS tweets (
    tweet_id        TEXT PRIMARY KEY,
    screen_name     TEXT,
    followers_count INTEGER DEFAULT 0,
    full_text       TEXT NOT NULL,
    created_at      TEXT,
    lang            TEXT,
    source          TEXT,
    intent_label    TEXT,
    sentiment       TEXT,
    embedding       TEXT,
    retweet_count   INTEGER DEFAULT 0,
    like_count      INTEGER DEFAULT 0,
    reply_count     INTEGER DEFAULT 0,
    view_count      INTEGER DEFAULT 0,
    user_location   TEXT,
    coded_by        TEXT,
    is_spam         INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tweet_causes (
    tweet_id          TEXT NOT NULL,
    cause_category    TEXT NOT NULL,
    matched_sentence  TEXT,
    FOREIGN KEY (tweet_id) REFERENCES tweets(tweet_id),
    PRIMARY KEY (tweet_id, cause_category)
);

CREATE TABLE IF NOT EXISTS tweet_products (
    tweet_id     TEXT NOT NULL,
    product_type TEXT NOT NULL,
    FOREIGN KEY (tweet_id) REFERENCES tweets(tweet_id),
    PRIMARY KEY (tweet_id, product_type)
);

CREATE TABLE IF NOT EXISTS tweet_brands (
    tweet_id        TEXT NOT NULL,
    brand_raw       TEXT NOT NULL,
    brand_canonical TEXT,
    FOREIGN KEY (tweet_id) REFERENCES tweets(tweet_id),
    PRIMARY KEY (tweet_id, brand_raw)
);

CREATE TABLE IF NOT EXISTS tweet_barriers (
    tweet_id     TEXT NOT NULL,
    barrier_code TEXT NOT NULL,
    coded_by     TEXT,
    FOREIGN KEY (tweet_id) REFERENCES tweets(tweet_id),
    PRIMARY KEY (tweet_id, barrier_code)
);

CREATE TABLE IF NOT EXISTS tweet_aspects (
    tweet_id  TEXT NOT NULL,
    aspect    TEXT NOT NULL,
    sentiment TEXT,
    span_text TEXT,
    FOREIGN KEY (tweet_id) REFERENCES tweets(tweet_id)
);
"""


# ---------------------------------------------------------------------------
# Database initialization
# ---------------------------------------------------------------------------

def init_db(db_path: str | Path | None = None) -> sqlite3.Connection:
    """
    Create the database and tables if they don't exist.
    Returns an open connection.
    """
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(CREATE_TABLES_SQL)
    conn.commit()

    logger.info(f"Database initialized at {path}")
    return conn


# ---------------------------------------------------------------------------
# Single tweet loading
# ---------------------------------------------------------------------------

def _load_one_tweet(conn: sqlite3.Connection, tweet: EnrichedTweet) -> None:
    """
    Insert or replace a single tweet and its child rows.

    Child tables use delete-then-insert to handle changes on re-runs.
    """
    # Serialize embedding as JSON array
    embedding_json = json.dumps(tweet.embedding) if tweet.embedding else None

    # Main tweets table — INSERT OR REPLACE
    conn.execute(
        """
        INSERT OR REPLACE INTO tweets (
            tweet_id, screen_name, followers_count, full_text, created_at,
            lang, source, intent_label, sentiment, embedding,
            retweet_count, like_count, reply_count, view_count,
            user_location, coded_by, is_spam
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            tweet.tweet_id,
            tweet.screen_name,
            tweet.followers_count,
            tweet.full_text,
            tweet.created_at,
            tweet.lang,
            tweet.source,
            tweet.intent_label.value,
            tweet.sentiment.value,
            embedding_json,
            tweet.retweet_count,
            tweet.like_count,
            tweet.reply_count,
            tweet.view_count,
            tweet.user_location,
            tweet.coded_by,
            1 if tweet.is_spam else 0,
        ),
    )

    # Delete existing child rows for this tweet (idempotent re-runs)
    for table in ["tweet_causes", "tweet_products", "tweet_brands", "tweet_barriers", "tweet_aspects"]:
        conn.execute(f"DELETE FROM {table} WHERE tweet_id = ?", (tweet.tweet_id,))

    # tweet_causes
    for cause in tweet.causes:
        conn.execute(
            "INSERT OR REPLACE INTO tweet_causes (tweet_id, cause_category, matched_sentence) VALUES (?, ?, ?)",
            (tweet.tweet_id, cause.cause_category.value, cause.matched_sentence),
        )

    # tweet_products
    for product in tweet.products:
        conn.execute(
            "INSERT OR IGNORE INTO tweet_products (tweet_id, product_type) VALUES (?, ?)",
            (tweet.tweet_id, product.value),
        )

    # tweet_brands
    for brand in tweet.brands_raw:
        canonical = tweet.brands_canonical.get(brand.brand_raw, brand.brand_raw)
        conn.execute(
            "INSERT OR IGNORE INTO tweet_brands (tweet_id, brand_raw, brand_canonical) VALUES (?, ?, ?)",
            (tweet.tweet_id, brand.brand_raw, canonical),
        )

    # tweet_barriers
    for barrier in tweet.barriers:
        conn.execute(
            "INSERT OR IGNORE INTO tweet_barriers (tweet_id, barrier_code, coded_by) VALUES (?, ?, ?)",
            (tweet.tweet_id, barrier.barrier_code.value, tweet.coded_by),
        )

    # tweet_aspects
    for aspect in tweet.aspects:
        conn.execute(
            "INSERT INTO tweet_aspects (tweet_id, aspect, sentiment, span_text) VALUES (?, ?, ?, ?)",
            (tweet.tweet_id, aspect.aspect.value, aspect.sentiment.value, aspect.span_text),
        )


# ---------------------------------------------------------------------------
# Batch loading
# ---------------------------------------------------------------------------

def load_all(
    tweets: list[EnrichedTweet],
    db_path: str | Path | None = None,
) -> None:
    """
    Stage 6: Load all enriched tweets into SQLite.

    Uses a single transaction for performance and atomicity.

    Args:
        tweets: List of enriched tweets from Stages 2-5.
        db_path: Path to corpus.db.
    """
    conn = init_db(db_path)

    try:
        for tweet in tweets:
            _load_one_tweet(conn, tweet)
        conn.commit()
        logger.info(f"Stage 6 complete: {len(tweets)} tweets loaded into database")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
