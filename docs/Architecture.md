# Hairfall Insights — ETL Pipeline Architecture

## Overview

Converts ~3500 scraped tweets into a structured, queryable SQLite database via an ELT pipeline powered by LLM extraction. Focus: **consumer barriers and perceptions for hair fall treatment products**.

**Core principle:** Transform unstructured text once, query forever. Every downstream analysis runs as a SQL query — no LLM calls needed after the initial enrichment.

---

## Pipeline Stages

```
merged_corpus.csv
     │
     ▼
[1] extract + clean
     │  (normalize text, parse metadata, flag spam)
     ▼
[2] enrich via LLM (per-tweet, temperature=0)
     │  (LLM JSON → Pydantic validation)
     ▼
[3] cache to llm_cache.json (keyed by tweet_id)
     │  (zero API cost on re-runs)
     ▼
[4] generate embeddings (per-tweet, local model)
     │  (all-MiniLM-L6-v2 → 384-dim vector)
     ▼
[5] post-process brand normalization
     │  (lookup table, not LLM)
     ▼
[6] load into corpus.db (INSERT OR REPLACE)
     │  (normalize into 5 relational tables)
     ▼
corpus.db ──► analysis scripts / SQL / dashboard
```

---

## Stage 1 — Extract + Clean

Pure preprocessing. No LLM involved.

**What happens:**
- Normalize slang and informal language
- Resolve text encoding, Unicode, URLs, mentions
- Parse metadata: hashtags, language, source app
- Flag spam via heuristics (excessive links, bot patterns, duplicates)
- Parse engagement metrics (view_count, like_count, retweet_count, reply_count)

**Output:** Clean in-memory tweet rows. Nothing written to DB yet.
This keeps the stage stateless — re-runs have no side effects.

---

## Stage 2 — LLM Enrichment

Each tweet is sent to the LLM with a structured prompt. Settings:

- `temperature = 0` — deterministic output
- **Per-tweet calls** (1 API call per tweet, not batched)
  - Rationale: 3.5k tweets is small; the `llm_cache.json` already makes the pipeline a one-time cost. Per-tweet is simpler to implement and debug.
- **Pydantic validation as the only gate** — no confidence threshold

**Prompt returns a single structured JSON:**

```json
{
  "intent": "complaining",
  "causes": ["stress", "water_quality"],
  "sentiment": "negative",
  "products": ["shampoo"],
  "barriers": ["ineffective"],
  "aspects": [
    {"aspect": "hair_quality", "sentiment": "negative", "span_text": "hair is falling out"}
  ]
}
```

**Pydantic schema** (defines what "valid" looks like):

```python
from pydantic import BaseModel

class ExtractedTweet(BaseModel):
    tweet_id: str
    intent: str                            # predefined closed enum
    causes: list[str]                      # predefined closed enum
    sentiment: str                         # "positive" / "negative" / "neutral"
    products: list[str]                    # product types mentioned
    barriers: list[str]                    # predefined closed enum
    aspects: list[dict]                    # {"aspect": str, "sentiment": str, "span_text": str}
```

**What Pydantic catches:** Missing fields, wrong types, malformed structure.
**What Pydantic doesn't catch:** Meaning errors (e.g., wrong cause label).

If validation fails → tweet goes to dead-letter log. No silent drops. No confidence gate fallback.

---

## Stage 3 — Cache

Raw LLM response written to `llm_cache.json` before any DB write.

```json
{
  "tweet_id_9001": {
    "response": { "intent": "complaining", "causes": [...], ... },
    "model": "deepseek-chat",
    "cached_at": "2026-05-26T10:00:00Z"
  }
}
```

**Why this matters:**
- Re-running the pipeline skips all API calls — only reads from cache
- Debugging — inspect actual LLM responses to tune prompts
- Audit trail — re-process from cache if schema changes, no re-scraping needed
- Reproducibility — same tweet always produces same output (deterministic + cached)

---

## Stage 4 — Embedding Generation

After LLM enrichment, generate vector embeddings for each tweet.

**Why:** Enables semantic search and cluster analysis for "unknown unknowns" discovery.

**Model:** `all-MiniLM-L6-v2`
- 384 dimensions
- Free, open-source, runs locally
- ~5 minutes for 3.5k tweets on CPU

**Output:** 384-dim float array stored as JSON string in `tweets.embedding` column.

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('all-MiniLM-L6-v2')

def embed_tweet(text: str) -> list[float]:
    embedding = model.encode(text, normalize_embeddings=True)
    return embedding.tolist()
```

**Embedding is generated per-tweet AFTER LLM extraction** — not before. This means:
- The embedding stage uses the cleaned `full_text` from Stage 1
- If LLM fails, no embedding is generated (skip dead-letter tweets)
- Re-runs can skip embedding if already stored (check if `embedding` column is not null)

---

## Stage 5 — Brand Normalization (Post-Processing)

After LLM extraction, brand names are normalized via a lookup table.

**Why post-processing instead of LLM:**
- Brand normalization is a deterministic lookup — not a reasoning task
- Cheap — just a dictionary lookup, no LLM needed
- Consistent — same input always gives same output
- Easy to update — add new entries to the lookup table, no re-extraction needed

**Process:**
1. LLM extracts `brand_raw` (as-written in tweet)
2. Post-process step: `brand_canonical = lookup_table.get(brand_raw, brand_raw)`
3. Unknown brands stay as raw — can be added to lookup table later

---

## Stage 5 — Load Into Database

Reads from `llm_cache.json` (not from LLM directly). Writes to `corpus.db` (SQLite).

**Idempotent:** `INSERT OR REPLACE BY tweet_id` — safe to re-runs.

**Why 5 tables instead of 1:**

One tweet can have multiple causes, brands, products, barriers, aspects. A flat table forces you to either:
- Cap columns at a fixed number (breaks on edge cases)
- Store arrays as JSON (breaks SQL aggregation)

Normalized tables solve this cleanly:

```
tweets (1) ──► tweet_causes (many)
tweets (1) ──► tweet_products (many)
tweets (1) ──► tweet_brands (many)
tweets (1) ──► tweet_barriers (many)
tweets (1) ──► tweet_aspects (many)
```

A tweet with 3 causes = 3 rows. SQL aggregation becomes natural.

---

## Database Schema — corpus.db

### tweets

| Column | Type | Notes |
|---|---|---|
| tweet_id | TEXT PK | Primary key, from Scweet |
| screen_name | TEXT | Twitter handle (merged from users) |
| followers_count | INTEGER | Follower count |
| full_text | TEXT | Original tweet text |
| created_at | TEXT | ISO timestamp |
| lang | TEXT | Tweet language (e.g., "in", "en") |
| source | TEXT | Platform/app (e.g., "IFTTT", "Twitter for iPhone") |
| intent_label | TEXT | Predefined closed enum |
| sentiment | TEXT | "positive" / "negative" / "neutral" |
| embedding | TEXT | JSON array of 384 floats — for semantic search & clustering |
| retweet_count | INTEGER | Engagement metric |
| like_count | INTEGER | Engagement metric |
| reply_count | INTEGER | Engagement metric |
| view_count | INTEGER | Reach metric |
| user_location | TEXT | User location (if available) |
| coded_by | TEXT | Model used |

### tweet_causes

| Column | Type | Notes |
|---|---|---|
| tweet_id | TEXT FK | Links to tweets |
| cause_category | TEXT | Predefined enum (e.g., "sulfates", "academic_stress") |
| confidence | FLOAT | LLM-reported only — not used as a gate |
| matched_sentence | TEXT | Snippet where cause was found |

### tweet_products

| Column | Type | Notes |
|---|---|---|
| tweet_id | TEXT FK | Links to tweets |
| product_type | TEXT | Predefined enum |
| product_raw | TEXT | As-written in tweet |

**Product type enum:**
```
shampoo
conditioner
treatment_mask
hair_oil
hair_serum
hair_tonic
supplement
medication
natural_remedy
professional_treatment
other
```

### tweet_brands

| Column | Type | Notes |
|---|---|---|
| tweet_id | TEXT FK | Links to tweets |
| brand_raw | TEXT | As-written in tweet (from LLM) |
| brand_canonical | TEXT | Normalized via lookup table (post-process) |

### tweet_barriers

| Column | Type | Notes |
|---|---|---|
| tweet_id | TEXT FK | Links to tweets |
| barrier_code | TEXT | Predefined enum |
| confidence | FLOAT | Not used as gate |
| coded_by | TEXT | Model used |

### tweet_aspects

| Column | Type | Notes |
|---|---|---|
| tweet_id | TEXT FK | Links to tweets |
| aspect | TEXT | Predefined grouped enum (sensory, usability, hair_quality, etc.) |
| sentiment | TEXT | "positive" / "negative" / "neutral" |
| span_text | TEXT | Exact text span from tweet |

---

## Predefined Enums

### intent_label

Predefined closed enum + "other" bucket.

```
discovery               — "anyone tried biotin for hair loss?"
complaining             — "this shampoo made my hair fall out"
seeking_recommendation  — "what shampoo actually works?"
sharing_success         — "finally found something that works!"
sharing_failure         — "another product that didn't help"
asking_question         — "is hair fall normal after pregnancy?"
venting                 — "I'm so frustrated with my hair"
other                   — anything that doesn't fit
```

### cause_category

```
stress
water_quality
product_ingredient
hormonal
nutrition_deficiency
genetics
scalp_condition
overprocessing
medication
seasonal
age
lifestyle
other
```

### barrier_code

```
price
side_effects
ineffective
lack_of_knowledge
no_trust
other
```

### aspect (grouped)

```
sensory                — smell, color, texture (how it looks/smells/feels)
usability              — application, absorption (ease of use)
hair_quality           — hair_texture, hair_volume, hair_strength (physical properties)
scalp_health           — scalp_condition, irritation (skin/scalp reactions)
effectiveness          — hair_fall_rate, growth_results (does it work?)
price_value            — value for money (price-related comments)
availability           — easy to find, out of stock (purchasing ease)
other
```

**Group rationale:** Grouping reduces complexity for the LLM to choose from. If a tweet mentions "smell is nice" → aspect = `sensory`. If it mentions "heavy on hair" → aspect = `sensory` (texture sub-group). The raw `span_text` still captures the exact phrase for detail analysis.

---

## Downstream Analysis

Every analysis runs as a SQL query. Milliseconds, no API cost, deterministic.

**Common patterns:**

```sql
-- Count tweets per cause (not cause-rows)
SELECT tc.cause_category, COUNT(DISTINCT t.tweet_id) as tweet_count
FROM tweets t
JOIN tweet_causes tc ON t.tweet_id = tc.tweet_id
GROUP BY tc.cause_category
ORDER BY tweet_count DESC

-- Causes filtered by sentiment
SELECT tc.cause_category, t.sentiment, COUNT(DISTINCT t.tweet_id) as n
FROM tweets t
JOIN tweet_causes tc ON t.tweet_id = tc.tweet_id
WHERE t.sentiment = 'negative'
GROUP BY tc.cause_category, t.sentiment

-- High-engagement complaints
SELECT tc.cause_category, AVG(t.like_count) as avg_likes
FROM tweets t
JOIN tweet_causes tc ON t.tweet_id = tc.tweet_id
WHERE t.intent_label = 'complaining'
GROUP BY tc.cause_category
ORDER BY avg_likes DESC

-- Brand vs cause cross-analysis
SELECT tb.brand_canonical, tc.cause_category, COUNT(*) as n
FROM tweets t
JOIN tweet_brands tb ON t.tweet_id = tb.tweet_id
JOIN tweet_causes tc ON t.tweet_id = tc.tweet_id
GROUP BY tb.brand_canonical, tc.cause_category
```

---

## What Was Considered and Deliberately Excluded

### Batching

**Not implemented for current scale.** Per-tweet calls are simpler and sufficient at 3.5k records. The `llm_cache.json` already makes the pipeline run-once. Batch if the pipeline scales to 100k+ records.

### Semantic Search Infrastructure (Qdrant/Chroma)

**Deferred.** Not included in MVP.

For 3.5k records, similarity search is handled in-memory (Python + numpy). No dedicated vector DB needed. If scale grows to 50k+ and real-time search is required, migrate to Qdrant or Chroma.

### Severity Field

**Excluded.** Emotional intensity is captured via:
- `intent_label` (venting, complaining vs discovery, sharing_success)
- `sentiment` (positive / negative / neutral)
- Engagement metrics (like_count, retweet_count) as indirect signal for impact

No dedicated severity number needed — intent + sentiment + engagement covers the analysis questions.

### Device Tier

**Excluded.** Redundant with `followers_count`. Influence tier can be derived in SQL when needed:

```sql
CASE
  WHEN followers_count > 5000 THEN 'high'
  WHEN followers_count > 500 THEN 'mid'
  ELSE 'low'
END as influence_tier
```

### Confidence Gate

**Not implemented.** The concept was in early drafts but is not meaningful:
- LLM-reported confidence is not a calibrated probability — it's a hallucinated number
- A threshold set without labeled data has no basis
- Pydantic schema validation is the real gate: if the response parses correctly, accept it

### Batching

**Not implemented for current scale.** Per-tweet calls are simpler and sufficient at 3.5k records. The `llm_cache.json` already makes the pipeline run-once. Batch if the pipeline scales to 100k+ records.

---

## Key Design Decisions

| Decision | Rationale |
|---|---|
| Per-tweet LLM calls | Simple to implement, no batch complexity, cache handles cost |
| Pydantic validation as gate | Real structural check; no reliance on unreliable confidence scores |
| Brand normalization post-processing | Deterministic, cheap, consistent, easy to update |
| 5 normalized tables | Enables SQL aggregation on one-to-many relationships |
| Merge users into tweets | User data is static for this analysis; simpler is better |
| llm_cache.json | Idempotency, debugging, audit trail, schema evolution |
| INSERT OR REPLACE | Safe re-runs; pipeline can be re-executed after schema changes |
| SQLite | Sufficient for 3.5k-100k records; zero ops overhead |
| No vector layer in MVP | Kept for later; in-memory Python handles 3.5k scale |

## Pipeline Run Scenarios

| Scenario | Behavior |
|---|---|
| First run | LLM called for all 3.5k tweets → cache → post-process → DB |
| Re-run | LLM skipped → read from cache → post-process → DB |
| Schema change (parsing) | Re-run reads cache → re-normalizes → DB (no LLM needed) |
| Schema change (new field) | Must re-run LLM — cache only stores what was extracted |
| One tweet fails validation | Dead-letter log (no silent drops) |
| Pipeline dies mid-run | Resume point: cache is already written; next run picks up from cache |

**Limitation:** If a new field is added to the schema after initial run, the original LLM response in cache won't contain it. Re-extraction is required. Keep raw text in `full_text` for ad-hoc analysis.

---

## Testing Strategy

Before running full scale, validate with a staged approach to minimize cost.

### Phase 1: Golden Set (~$0)
Manually label 30 tweets covering different scenarios (complaining, discovery, Indonesian text, English text, edge cases).

### Phase 2: 50-Tweet Test Batch (~$0.01)
Run pipeline on 50 tweets. Validate:
- Pydantic validation failure rate
- Output quality vs golden set
- SQL queries work as expected

### Phase 3: Full Scale (~$0.50)
Only if Phase 2 passes (>=85% accuracy on golden set).

**Cost estimate (DeepSeek API):**
- ~300 tokens per tweet (input + output)
- ~$0.00013 per tweet
- 3500 tweets ≈ **~$0.50** total

### Phase 4: Logic Validation (~$0)
After any code/prompt change, re-run parsing from `llm_cache.json` — no API calls.

---

## Schema Evolution Note

When the schema changes (new fields added):
1. Check if the field was in the original LLM prompt → if yes, re-run from cache (free)
2. If the field was NOT in the original prompt → must re-run LLM (cost applies)

Always keep `full_text` intact — it's the fallback for ad-hoc analysis when schema doesn't cover it.

---

## File Structure

```
docs/
├── Project_Objective.md    ← what we're building
├── Architecture.md         ← this file (current)

umarketmaker/
├── pipeline/
│   ├── extract_clean.py    ← Stage 1
│   ├── llm_enrich.py       ← Stage 2
│   ├── cache_llm.py         ← Stage 3
│   ├── generate_embeddings.py  ← Stage 4
│   ├── brand_normalize.py  ← Stage 5
│   ├── load_db.py          ← Stage 6
│   └── schema.py           ← Pydantic models
├── data/
│   ├── merged_corpus.csv   ← raw input
│   ├── llm_cache.json     ← LLM responses (cache)
│   ├── dead_letter.json    ← failed validations
│   └── corpus.db          ← final database
├── analysis/
│   ├── barrier_pipeline.py
│   ├── cause_analysis.py
│   └── brand_health.py
├── tests/
│   └── golden_set.json     ← manually labeled tweets
└── config/
    └── lookup_tables/
        └── brand_canonical.json
```