"""
Stage 4 — Embedding Generation

Generates 384-dimensional vector embeddings for each tweet using
all-MiniLM-L6-v2 (runs locally, free, ~80MB download on first run).

Embeddings are stored as JSON arrays in the tweets.embedding column
for later semantic search and cluster analysis.
"""

from __future__ import annotations

import logging
from typing import Optional

from .schema import EnrichedTweet

logger = logging.getLogger(__name__)


def generate_embeddings(
    tweets: list[EnrichedTweet],
    batch_size: int = 64,
    model_name: str = "all-MiniLM-L6-v2",
) -> list[EnrichedTweet]:
    """
    Stage 4: Generate vector embeddings for each tweet.

    Uses batch encoding for performance (~5 min for 3.5k tweets on CPU).
    Skips tweets that already have embeddings.

    Args:
        tweets: List of enriched tweets from Stage 2/3.
        batch_size: Batch size for the encoder.
        model_name: Sentence transformer model name.

    Returns:
        Same list with embedding fields populated.
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise ImportError(
            "sentence-transformers package is required. "
            "Install with: pip install sentence-transformers"
        )

    # Separate tweets that need embeddings vs already have them
    needs_embedding = [t for t in tweets if t.embedding is None]
    already_done = len(tweets) - len(needs_embedding)

    if not needs_embedding:
        logger.info("Stage 4: All tweets already have embeddings, skipping")
        return tweets

    logger.info(
        f"Stage 4: Generating embeddings for {len(needs_embedding)} tweets "
        f"({already_done} already done)"
    )

    # Load model (downloads on first run)
    logger.info(f"Loading model: {model_name}")
    model = SentenceTransformer(model_name)

    # Batch encode for performance
    texts = [t.full_text for t in needs_embedding]

    try:
        from tqdm import tqdm
        logger.info(f"Encoding {len(texts)} texts in batches of {batch_size}...")
        embeddings = model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=True,
        )
    except ImportError:
        embeddings = model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
        )

    # Assign embeddings back to tweets
    for tweet, embedding in zip(needs_embedding, embeddings):
        tweet.embedding = embedding.tolist()

    logger.info(f"Stage 4 complete: {len(needs_embedding)} embeddings generated")
    return tweets
