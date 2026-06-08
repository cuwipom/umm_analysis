"""
Stage 2 — LLM Enrichment

Sends each tweet to DeepSeek (OpenAI-compatible API) with a structured prompt.
Validates the response through Pydantic; failed validations go to dead_letter.json.

Settings (from Architecture.md):
- temperature = 0 (deterministic)
- Per-tweet calls (not batched)
- Pydantic validation as the only gate — no confidence threshold
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from .cache_llm import (
    DEFAULT_CACHE_PATH,
    get_cached,
    is_cached,
    load_cache,
    save_cache,
    set_cached,
)
from .schema import (
    CleanedTweet,
    EnrichedTweet,
    LLMResponse,
)

logger = logging.getLogger(__name__)

DEFAULT_DEAD_LETTER_PATH = Path(__file__).resolve().parent.parent / "pipeline_output" / "dead_letter.json"

# Model configuration
MODEL_NAME = "deepseek-chat"
API_BASE_URL = "https://api.deepseek.com"

# Retry / rate-limit settings
MAX_RETRIES = 3
RETRY_DELAY = 2.0  # seconds
CALL_DELAY = 0.1   # seconds between calls


# ---------------------------------------------------------------------------
# System prompt — instructs the LLM on output format
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a text analysis assistant. You analyze tweets about hair care and hair fall.

Given a tweet, extract structured information and return ONLY a valid JSON object with these exact fields:

{
  "intent": "<one of: discovery, complaining, seeking_recommendation, sharing_success, sharing_failure, asking_question, venting, other>",
  "causes": [
    {"cause_category": "<one of: stress, water_quality, product_ingredient, hormonal, nutrition_deficiency, genetics, scalp_condition, overprocessing, medication, seasonal, age, lifestyle, other>", "matched_sentence": "<snippet from tweet>"}
  ],
  "sentiment": "<one of: positive, negative, neutral>",
  "products": ["<one of: shampoo, conditioner, treatment_mask, hair_oil, hair_serum, hair_tonic, supplement, medication, natural_remedy, professional_treatment, other>"],
  "barriers": [
    {"barrier_code": "<one of: price, side_effects, ineffective, lack_of_knowledge, no_trust, other>"}
  ],
  "aspects": [
    {"aspect": "<one of: sensory, usability, hair_quality, scalp_health, effectiveness, price_value, availability, other>", "sentiment": "<positive/negative/neutral>", "span_text": "<exact text span from tweet>"}
  ],
  "brands_raw": [
    {"brand_raw": "<brand name as written in tweet>", "product_type": "<product type or null>"}
  ]
}

Rules:
- Return ONLY the JSON object, no other text.
- Use empty arrays [] if a field has no values (e.g., no brands mentioned).
- For causes, only extract actual triggers or catalysts of hair loss (e.g., stress, bleaching, hormones, diet, genetics). Do NOT extract the symptom of hair fall itself (e.g., 'rambut rontok', 'my hair falls out') as a cause. If no underlying trigger is mentioned, causes MUST be an empty array [].
- For causes and aspects, include the matched_sentence/span_text from the original tweet.
- The tweet may be in Indonesian (Bahasa Indonesia) or English. Analyze regardless of language.
- Focus on consumer barriers and perceptions for hair fall treatment products.
- Be conservative: only extract what is clearly stated or strongly implied."""


# ---------------------------------------------------------------------------
# LLM Response Normalizer
# ---------------------------------------------------------------------------

def _normalize_raw_response(raw: dict) -> dict:
    """
    Clean and map raw LLM response fields to match strict Pydantic enums.
    This prevents minor formatting issues (e.g. spaces vs underscores,
    out-of-scope products, synonym intents) from breaking validation.
    """
    if not isinstance(raw, dict):
        return raw

    # Copy raw to avoid mutating the original dict in place during loops
    raw = dict(raw)

    # 1. Normalize intent
    intent = str(raw.get("intent", "")).strip().lower()
    allowed_intents = {
        "discovery", "complaining", "seeking_recommendation", 
        "sharing_success", "sharing_failure", "asking_question", 
        "venting", "other"
    }
    intent_mapping = {
        "recommendation": "seeking_recommendation",
        "sharing_information": "other",
        "sharing_experience": "other",
        "sharing_discovery": "other",
        "promotion": "other"
    }
    if intent in intent_mapping:
        raw["intent"] = intent_mapping[intent]
    elif intent not in allowed_intents:
        raw["intent"] = "other"
    else:
        raw["intent"] = intent

    # Helper for product cleanup
    allowed_products = {
        "shampoo", "conditioner", "treatment_mask", "hair_oil", 
        "hair_serum", "hair_tonic", "supplement", "medication", 
        "natural_remedy", "professional_treatment", "other"
    }
    
    def clean_product(p: str) -> str:
        p_clean = str(p).strip().lower().replace(" ", "_")
        product_mapping = {
            "haircare": "other",
            "hair_care": "other",
            "hair": "other",
            "hair_lotion": "hair_tonic",  # Zwitsal hair lotion maps best to tonic/other
            "hair_cream": "other",
            "hair_dryer": "other",
            "hair_spray": "other",
            "heat_protectant": "other",
            "hair_color": "other",
            "toner": "other",
            "body_lotion": "other",
            "body_wash": "other",
            "body_scrub": "other",
            "cushion": "other",
            "moisturizer": "other",
            "dry_shampoo": "shampoo",
            "hair_mask": "treatment_mask",
            "hair_vitamin": "supplement"
        }
        if p_clean in product_mapping:
            return product_mapping[p_clean]
        if p_clean in allowed_products:
            return p_clean
        return "other"

    # 2. Normalize products list
    products = raw.get("products")
    if isinstance(products, list):
        raw["products"] = [clean_product(p) for p in products]
    else:
        raw["products"] = []

    # 3. Normalize brands_raw list
    brands = raw.get("brands_raw")
    if isinstance(brands, list):
        cleaned_brands = []
        for brand in brands:
            if isinstance(brand, dict):
                brand = dict(brand)
                pt = brand.get("product_type")
                if pt is not None:
                    brand["product_type"] = clean_product(pt)
                cleaned_brands.append(brand)
        raw["brands_raw"] = cleaned_brands

    # 4. Normalize causes
    causes = raw.get("causes")
    allowed_causes = {
        "stress", "water_quality", "product_ingredient", "hormonal", 
        "nutrition_deficiency", "genetics", "scalp_condition", 
        "overprocessing", "medication", "seasonal", "age", 
        "lifestyle", "other"
    }
    if isinstance(causes, list):
        cleaned_causes = []
        for cause in causes:
            if isinstance(cause, dict):
                cause = dict(cause)
                cat = str(cause.get("cause_category", "")).strip().lower().replace(" ", "_")
                if cat == "weather":
                    cat = "seasonal"
                if cat not in allowed_causes:
                    cat = "other"
                cause["cause_category"] = cat
                cleaned_causes.append(cause)
        raw["causes"] = cleaned_causes

    # 5. Normalize barriers
    barriers = raw.get("barriers")
    allowed_barriers = {
        "price", "side_effects", "ineffective", "lack_of_knowledge", 
        "no_trust", "other"
    }
    if isinstance(barriers, list):
        cleaned_barriers = []
        for b in barriers:
            if isinstance(b, dict):
                b = dict(b)
                code = str(b.get("barrier_code", "")).strip().lower().replace(" ", "_")
                if code in {"availability", "sensory"}:
                    code = "other"
                if code not in allowed_barriers:
                    code = "other"
                b["barrier_code"] = code
                cleaned_barriers.append(b)
        raw["barriers"] = cleaned_barriers

    # 6. Normalize aspects
    aspects = raw.get("aspects")
    allowed_aspects = {
        "sensory", "usability", "hair_quality", "scalp_health", 
        "effectiveness", "price_value", "availability", "other"
    }
    if isinstance(aspects, list):
        cleaned_aspects = []
        for a in aspects:
            if isinstance(a, dict):
                a = dict(a)
                aspect = str(a.get("aspect", "")).strip().lower().replace(" ", "_")
                if aspect in {"ingredients", "ingredient"}:
                    aspect = "other"
                if aspect not in allowed_aspects:
                    aspect = "other"
                a["aspect"] = aspect
                cleaned_aspects.append(a)
        raw["aspects"] = cleaned_aspects

    # 7. Normalize sentiment
    sentiment = str(raw.get("sentiment", "")).strip().lower()
    allowed_sentiments = {"positive", "negative", "neutral"}
    if sentiment not in allowed_sentiments:
        raw["sentiment"] = "neutral"
    else:
        raw["sentiment"] = sentiment

    return raw


# ---------------------------------------------------------------------------
# LLM Client
# ---------------------------------------------------------------------------

def _get_client():
    """Create an OpenAI-compatible client for DeepSeek."""
    try:
        # pyrefly: ignore [missing-import]
        from openai import OpenAI
    except ImportError:
        raise ImportError("openai package is required. Install with: pip install openai")

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "DEEPSEEK_API_KEY environment variable is not set. "
            "Set it with: export DEEPSEEK_API_KEY=your_key_here"
        )

    return OpenAI(api_key=api_key, base_url=API_BASE_URL)


def _call_llm(client, tweet_text: str) -> dict:
    """
    Send a single tweet to the LLM and return the parsed JSON response.

    Raises ValueError if the response is not valid JSON.
    """
    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": tweet_text},
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            if not content:
                raise ValueError("Empty response from LLM")

            return json.loads(content)

        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error (attempt {attempt + 1}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
            else:
                raise ValueError(f"Failed to parse LLM response as JSON after {MAX_RETRIES} attempts")

        except Exception as e:
            logger.warning(f"LLM call error (attempt {attempt + 1}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))  # exponential-ish backoff
            else:
                raise


# ---------------------------------------------------------------------------
# Dead letter logging
# ---------------------------------------------------------------------------

def _append_dead_letter(
    dead_letter_path: Path,
    tweet_id: str,
    tweet_text: str,
    error: str,
    raw_response: Optional[dict] = None,
) -> None:
    """Append a failed tweet to the dead-letter log."""
    entries = []
    if dead_letter_path.exists():
        with open(dead_letter_path, "r", encoding="utf-8") as f:
            entries = json.load(f)

    entries.append({
        "tweet_id": tweet_id,
        "tweet_text": tweet_text[:200],
        "error": str(error),
        "raw_response": raw_response,
        "failed_at": datetime.now(timezone.utc).isoformat(),
    })

    dead_letter_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dead_letter_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Main enrichment function
# ---------------------------------------------------------------------------

def enrich_tweets(
    tweets: list[CleanedTweet],
    cache_path: Optional[str | Path] = None,
    dead_letter_path: Optional[str | Path] = None,
    skip_llm: bool = False,
) -> tuple[list[EnrichedTweet], int]:
    """
    Stage 2+3: Enrich tweets via LLM and cache responses.

    Args:
        tweets: List of cleaned tweets from Stage 1.
        cache_path: Path to llm_cache.json.
        dead_letter_path: Path to dead_letter.json.
        skip_llm: If True, only use cached responses (no API calls).

    Returns:
        Tuple of (enriched_tweets, dead_letter_count).
    """
    c_path = Path(cache_path) if cache_path else DEFAULT_CACHE_PATH
    dl_path = Path(dead_letter_path) if dead_letter_path else DEFAULT_DEAD_LETTER_PATH

    cache = load_cache(c_path)
    client = None if skip_llm else _get_client()

    enriched: list[EnrichedTweet] = []
    dead_letter_count = 0
    cache_hits = 0
    api_calls = 0
    save_interval = 10  # Save cache every N new entries

    try:
        from tqdm import tqdm
        iterator = tqdm(tweets, desc="Enriching tweets", unit="tweet")
    except ImportError:
        iterator = tweets

    for tweet in iterator:
        # Skip spam-flagged tweets
        if tweet.is_spam:
            continue

        # Check cache first
        cached_response = get_cached(cache, tweet.tweet_id)
        if cached_response is not None:
            cache_hits += 1
            try:
                cleaned_cached = _normalize_raw_response(cached_response)
                llm_resp = LLMResponse.model_validate(cleaned_cached)
                enriched_tweet = EnrichedTweet.from_cleaned_and_llm(
                    tweet, llm_resp, model_name=cache[tweet.tweet_id].get("model", "cached")
                )
                enriched.append(enriched_tweet)
            except ValidationError as e:
                logger.warning(f"Cached response for {tweet.tweet_id} failed re-validation: {e}")
                _append_dead_letter(dl_path, tweet.tweet_id, tweet.full_text, str(e), cached_response)
                dead_letter_count += 1
            continue

        # No cache hit — call LLM (unless skip_llm)
        if skip_llm:
            continue

        try:
            raw_response = _call_llm(client, tweet.full_text)
            api_calls += 1

            # Clean and normalize raw response fields
            cleaned_response = _normalize_raw_response(raw_response)

            # Validate through Pydantic
            llm_resp = LLMResponse.model_validate(cleaned_response)

            # Cache the validated response
            set_cached(cache, tweet.tweet_id, cleaned_response, MODEL_NAME)

            # Build enriched tweet
            enriched_tweet = EnrichedTweet.from_cleaned_and_llm(
                tweet, llm_resp, model_name=MODEL_NAME
            )
            enriched.append(enriched_tweet)

            # Periodic cache save
            if api_calls % save_interval == 0:
                save_cache(cache, c_path)

            # Rate limiting
            time.sleep(CALL_DELAY)

        except ValidationError as e:
            logger.warning(f"Tweet {tweet.tweet_id} LLM response failed validation: {e}")
            _append_dead_letter(dl_path, tweet.tweet_id, tweet.full_text, str(e), raw_response)
            dead_letter_count += 1

        except Exception as e:
            logger.error(f"Tweet {tweet.tweet_id} LLM call failed: {e}")
            _append_dead_letter(dl_path, tweet.tweet_id, tweet.full_text, str(e))
            dead_letter_count += 1

    # Final cache save
    save_cache(cache, c_path)

    logger.info(
        f"Stage 2 complete: {len(enriched)} enriched, "
        f"{cache_hits} cache hits, {api_calls} API calls, "
        f"{dead_letter_count} dead-lettered"
    )

    return enriched, dead_letter_count
