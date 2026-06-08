"""
Stage 5 — Brand Normalization (Post-Processing)

Normalizes brand names via a deterministic lookup table.
Not an LLM task — just a dictionary lookup.

Why post-processing (from Architecture.md):
- Deterministic: same input → same output
- Cheap: no API calls
- Easy to update: add entries to brand_canonical.json
"""

from __future__ import annotations

import difflib
import json
import logging
from pathlib import Path

from .schema import EnrichedTweet

logger = logging.getLogger(__name__)

DEFAULT_LOOKUP_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "lookup_tables" / "brand_canonical.json"
)

# Set of lowercase keywords and stopwords that represent noise rather than real brands.
NOISE_KEYWORDS = {
    # Indonesian stopwords & conversational noise
    "sama", "yg", "yang", "dan", "di", "ke", "dari", "itu", "ini", "untuk",
    "ada", "bisa", "buat", "aja", "ga", "gak", "ya", "dgn", "utk", "krn",
    "karena", "tapi", "tp", "lah", "kok", "sih", "juga", "jg", "kalau", "kalo",
    "mau", "pas", "ah", "eh", "oh", "deh", "dong", "saja", "sore", "pagi",
    "siang", "malam", "hari", "bulan", "tahun", "kali", "orang", "anak", "ibu",
    "bapak", "kak", "bang", "sis", "gan", "bro", "ituu", "iniii", "mu", "kok",
    "nih", "tuh", "guys", "rek", "nderr", "nder", "teh", "neng", "mas", "mbak",
    "nya", "punya", "jadi", "jd", "dengan", "dulu", "dulunya", "duluu", "dongg",
    "bgt", "banget", "lu", "luw", "kamu", "aku", "gua", "gw", "gue", "lo", "elo",
    "ituuu", "iniii", "pl", "mu", "t1", "kf", "gaa", "gakk", "yangg", "dann", "dia",
    "mereka", "kita", "kami", "kamuu", "iniii", "sihh", "donggg", "dah", "udah",
    "sudah", "belum", "blm", "habis", "hbs", "setelah", "sebelum",
    
    # English stopwords & generic words
    "the", "and", "for", "with", "that", "this", "have", "here", "there", "from",
    "your", "them", "their", "about", "best", "find", "link", "bio", "shopee",
    "tiktok", "tokopedia", "instagram", "twitter", "ig", "tw", "fb", "facebook",
    
    # Generic skincare/makeup/cosmetic categories
    "cushion", "cermin", "lip balm", "lipbalm", "mascara", "maskara", "eyeliner",
    "foundation", "sunscreen", "moisturizer", "toner", "cleanser", "clay mask",
    "sheet mask", "lip tint", "liptint", "lipstick", "lipstik", "powder",
    "concealer", "blush", "blush on", "highlighter", "eyeshadow", "makeup", "make up",
    "skincare", "skin care", "bodycare", "body care", "body lotion", "bodylotion",
    "facewash", "face wash", "facemist", "face mist", "micellar water",
    "sun block", "sunblock", "acne patch", "acne", "serum", "shampoo",
    "conditioner", "hair care", "haircare", "hair oil", "hairoil", "hair serum",
    "hairtonic", "hair tonic", "hair vitamin", "hairvitamin", "treatment",
    "hair treatment", "masker", "masker rambut", "tonic", "tonik", "shampooo",
    "shampoonya", "shampounya", "kondisioner", "shampo", "sampo", "creambath",
    "cream bath", "hair mask", "hairmask", "oil", "oils", "serums", "tonics",
    
    # Common generic hair ingredients/symptom words (unless part of a brand name)
    "minyak kemiri", "kemiri", "ginseng", "kemirinya", "rosemary", "rosemary oil",
    "rosemary hair oil", "aloe vera", "aloevera", "coconut oil", "castor oil",
    "argan oil", "tea tree", "biotin", "keratin", "collagen", "zinc",
    "hair fall", "hair loss", "rontok", "ketombe", "lepek", "botak", "ketombean",
    "rontok parah", "rambut rontok", "rambut", "panax ginseng", "panax",
    
    # Affiliate / spam indicators
    "best find", "best find 2026", "bestfind", "shopee find", "shopee finds",
    "rekomendasi", "racun shopee", "racun shopee murah", "link shopee",
    "link bio", "affiliate", "spill link", "spill", "co", "check out",
    "keranjang kuning", "toko oren", "toko ijo", "racun", "murmer",

    # Non-hair brand names, electronics, countries, miscellaneous noise
    "jepang", "jepun", "japan", "india", "korea", "china", "indonesia", "malaysia",
    "thailand", "singapore", "singapura", "jerman", "prancis", "amerika", "boboiboy",
    "tupperware", "lion star", "lionstar", "halodoc", "mamanya zavi", "lakik",
    "kuda", "huawei", "hisense", "apple", "samsung", "xiaomi", "oppo", "vivo",
    "realme", "asus", "lenovo", "hp", "dell", "acer", "sony", "panasonic", "lg",
    "jiniso", "jiniso jeans", "condi", "crembath", "airbot", "abc", "watsons",
    "bugaboo", "cottonink", "centrum", "doremi", "b'nite", "expect", "eman", "final sintra", "final"
}

# Substring matches to discard
NOISE_SUBSTRINGS = [
    "best find",
    "link bio",
    "shopee find",
    "racun shopee",
    "spill link",
    "keranjang kuning",
    "toko oren",
    "toko ijo",
    "link shopee",
    "toko orange"
]


def is_noise(brand_raw: str, lookup: dict[str, str]) -> bool:
    """
    Check if a raw brand name is noise.
    
    Returns True if the string is considered noise, False otherwise.
    """
    brand_clean = brand_raw.lower().strip()
    
    # 1. If it's explicitly in the lookup table keys or values, it is NOT noise
    if brand_clean in lookup or brand_clean in [v.lower() for v in lookup.values()]:
        return False
        
    # 2. Length-based checks (very short tokens like "pl", "mu", "kf", unless they were in lookup)
    if len(brand_clean) < 3:
        return True
        
    # 3. Contains no alphabetic characters (e.g. numbers, symbols only)
    if not any(char.isalpha() for char in brand_clean):
        return True
        
    # 4. Exact match in noise keywords
    if brand_clean in NOISE_KEYWORDS:
        return True
        
    # 5. Substring search for common spam/affiliate noise
    for sub in NOISE_SUBSTRINGS:
        if sub in brand_clean:
            return True
            
    return False


def load_lookup_table(path: str | Path | None = None) -> dict[str, str]:
    """Load the brand canonical lookup table."""
    lookup_path = Path(path) if path else DEFAULT_LOOKUP_PATH
    if not lookup_path.exists():
        logger.warning(f"Brand lookup table not found at {lookup_path}, using empty table")
        return {}

    with open(lookup_path, "r", encoding="utf-8") as f:
        table = json.load(f)

    logger.info(f"Loaded brand lookup table with {len(table)} entries")
    return table


def normalize_brand(brand_raw: str, lookup: dict[str, str]) -> str:
    """
    Normalize a single brand name.
    
    1. Direct dictionary match (handles exact lookups and manual typo mappings).
    2. Fuzzy match fallback against known dictionary keys (using difflib).
    3. Fallback to raw brand name if no match found.
    """
    brand_clean = brand_raw.lower().strip()
    
    # 1. Direct dictionary match
    if brand_clean in lookup:
        return lookup[brand_clean]
        
    # 2. Fuzzy match fallback (using a similarity threshold of 0.8)
    close_matches = difflib.get_close_matches(brand_clean, lookup.keys(), n=1, cutoff=0.8)
    if close_matches:
        matched_key = close_matches[0]
        logger.debug(f"Fuzzy matched raw brand '{brand_raw}' -> '{lookup[matched_key]}' (via '{matched_key}')")
        return lookup[matched_key]
        
    # 3. Fallback
    return brand_raw


def normalize_brands(
    tweets: list[EnrichedTweet],
    lookup_path: str | Path | None = None,
) -> list[EnrichedTweet]:
    """
    Stage 5: Normalize brand names across all tweets.

    Filters out brand noise (stopwords, generic terms, short junk)
    and populates the brands_canonical dict on each EnrichedTweet:
      { "pantene": "Pantene", "loreal": "L'Oréal" }

    Args:
        tweets: List of enriched tweets from Stage 4.
        lookup_path: Path to brand_canonical.json.

    Returns:
        Same list with noise filtered from brands_raw and brands_canonical populated.
    """
    lookup = load_lookup_table(lookup_path)

    unknown_brands: set[str] = set()
    normalized_count = 0
    filtered_noise_count = 0

    for tweet in tweets:
        filtered_brands_raw = []
        canonical_map: dict[str, str] = {}
        
        for brand_mention in tweet.brands_raw:
            raw = brand_mention.brand_raw
            
            # Filter out noise
            if is_noise(raw, lookup):
                filtered_noise_count += 1
                logger.debug(f"Filtered out noise brand mention: '{raw}' in tweet {tweet.tweet_id}")
                continue
                
            canonical = normalize_brand(raw, lookup)
            canonical_map[raw] = canonical
            filtered_brands_raw.append(brand_mention)

            if raw.lower().strip() not in lookup:
                unknown_brands.add(raw)
            else:
                normalized_count += 1

        tweet.brands_raw = filtered_brands_raw
        tweet.brands_canonical = canonical_map

    if unknown_brands:
        logger.info(
            f"Stage 5: {len(unknown_brands)} unknown brands (not in lookup table): "
            f"{sorted(unknown_brands)[:10]}..."
        )

    logger.info(
        f"Stage 5 complete: {normalized_count} brand mentions normalized, "
        f"{filtered_noise_count} noise mentions discarded, "
        f"{len(unknown_brands)} unknown"
    )

    return tweets
