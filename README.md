# Hairfall Insights: ETL & LLM Text Analytics Pipeline

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Database: SQLite / BigQuery](https://img.shields.io/badge/database-SQLite%20%2F%20BigQuery-orange.svg)]()
[![LLM: DeepSeek / OpenAI API](https://img.shields.io/badge/LLM-DeepSeek%20%2F%20OpenAI-green.svg)]()

A robust, cost-effective **ELT (Extract, Load, Transform)** data pipeline that crawls unstructured social media text (Twitter/X) and uses Large Language Models (LLMs) and local sentence transformers to generate a structured, semantic relational database. 

Designed for **consumer insight analytics**, this project focuses on mapping consumer barriers and triggers regarding hair loss and hair care treatment products.

---

## 1. Executive Summary

### The Challenge
Social media discussions are rich in organic consumer feedback, but the text is messy, filled with typos, emojis, and slang. Running direct LLM queries over large datasets to extract insights is slow, expensive, non-deterministic, and prone to API rate limits.

This pipeline decouples the **semantic parsing** stage from the **analytical** stage:
1. **Extract and Clean:** Processes raw Twitter datasets and flags spam using heuristics.
2. **LLM JSON Mode + Pydantic validation:** Standardizes unstructured text into a single-pass JSON payload ( Sentiment, Intent, Causes, Product Types, and Barriers).
3. **Atomic File Caching:** Saves LLM outputs locally, meaning subsequent pipeline runs run at **zero API cost**.
4. **Local Embeddings:** Generates 384-dimensional vector embeddings locally using `all-MiniLM-L6-v2` for semantic search and cluster analysis.
5. **Relational Database Loader:** Writes normalized records to 5 relational tables in SQLite (and exports to BigQuery), enabling **instant, free SQL-based analytical queries**.

---

## 2. Pipeline Architecture

```
                                [Raw CSV Batches]
                                        │
                                        ▼
    Stage 1: Extract + Clean ───────────► Normalize text, parse metadata, flag spam
                                        │
                                        ▼
    Stage 2: LLM Enrichment ────────────► DeepSeek JSON Mode + Pydantic Validation
                                        │
    Stage 3: Cache (llm_cache.json) ◄───┴───► Skips API on re-runs (zero cost)
                                        │
                                        ▼
    Stage 4: Generate Embeddings ───────► Local SentenceTransformer (384-dim)
                                        │
                                        ▼
    Stage 5: Brand Normalization ───────► Fast lookup-table mapping (no LLMs)
                                        │
                                        ▼
    Stage 6: SQLite / BigQuery Loader ──► Populate 6-table normalized schema
                                        │
                                        ▼
                             [Downstream SQL Analytics]
```

---

## 3. Project Structure

```
umarketmaker/
├── config/
│   ├── cookies.txt               # Scraper authorization tokens (for rotation)
│   └── lookup_tables/
│       └── brand_canonical.json  # Brand normalization mapping rules
├── data/
│   ├── processed/                # Merged, deduplicated, and normalized inputs
│   └── raw/                      # Raw batches of scraped CSV files
├── pipeline/
│   ├── __init__.py
│   ├── run_pipeline.py           # Pipeline Orchestrator (CLI entrypoint)
│   ├── schema.py                 # Pydantic models & validation rules
│   ├── extract_clean.py          # Stage 1: Data extraction & text cleaning
│   ├── llm_enrich.py             # Stage 2: LLM text enrichment
│   ├── cache_llm.py              # Stage 3: Atomic file cache
│   ├── generate_embeddings.py    # Stage 4: Sentence embeddings generation
│   ├── brand_normalize.py        # Stage 5: Brand normalization lookup
│   └── load_db.py                # Stage 6: Database initialization & loading
├── pipeline_output/
│   ├── corpus.db                 # Generated SQLite relational database
│   ├── llm_cache.json            # Local cache of LLM API responses
│   ├── dead_letter.json          # Failed validations for pipeline auditing
│   └── bq_exports/               # BigQuery-ready CSV tables
├── script/
│   ├── scweet.py                 # Scraper rotation utility (via Scweet)
│   ├── merge_and_clean.py        # Cleans and deduplicates scraped batches
│   ├── export_to_csv.py          # Exports SQLite tables to CSV
│   └── load_to_bq.py             # Uploads CSV tables to Google Cloud BigQuery
├── tests/
│   └── golden_set.json           # Labeled tweets for logic & prompt evaluation
├── requirements.txt              # Project dependencies
├── .env.example                  # Template environment file
└── README.md                     # Main portfolio page (this file)
```

---

## 4. Database Schema

The pipeline populates a normalized **6-table schema** inside SQLite (`corpus.db`), which splits one-to-many relationship dimensions to make aggregations simple.

### `tweets` (Core Table)
| Column | Type | Description |
|---|---|---|
| `tweet_id` | TEXT (PK) | Unique Twitter status identifier |
| `screen_name` | TEXT | Twitter handle |
| `followers_count` | INTEGER | User follower count (influence signal) |
| `full_text` | TEXT | Preprocessed, cleaned tweet text |
| `created_at` | TEXT | Timestamp in ISO format |
| `lang` | TEXT | Tweet language (e.g. `in` for Indonesian, `en` for English) |
| `source` | TEXT | App source (e.g., "Twitter for Android") |
| `intent_label` | TEXT | Class of intent (`venting`, `complaining`, `seeking_recommendation`, etc.) |
| `sentiment` | TEXT | Sentiment tag (`positive`, `negative`, `neutral`) |
| `embedding` | TEXT | JSON stringified 384-dimensional vector embedding |
| `retweet_count` | INTEGER | Retweet count |
| `like_count` | INTEGER | Like count |
| `reply_count` | INTEGER | Reply/comment count |
| `view_count` | INTEGER | Impression count |
| `user_location` | TEXT | Location string if shared in profile |
| `coded_by` | TEXT | LLM model version that processed the tweet |

### `tweet_causes`
| Column | Type | Description |
|---|---|---|
| `tweet_id` | TEXT (FK) | References `tweets.tweet_id` |
| `cause_category` | TEXT | Tagged cause (e.g. `stress`, `water_quality`, `genetics`, `scalp_condition`) |
| `confidence` | REAL | Model-reported classification confidence |
| `matched_sentence` | TEXT | Exact sentence matching the cause |

### `tweet_products`
| Column | Type | Description |
|---|---|---|
| `tweet_id` | TEXT (FK) | References `tweets.tweet_id` |
| `product_type` | TEXT | Standard product type (e.g., `shampoo`, `hair_serum`, `medication`) |
| `product_raw` | TEXT | Raw brand/product string parsed from the tweet |

### `tweet_brands`
| Column | Type | Description |
|---|---|---|
| `tweet_id` | TEXT (FK) | References `tweets.tweet_id` |
| `brand_raw` | TEXT | Raw brand name extracted by the LLM |
| `brand_canonical` | TEXT | Canonical brand name mapping from `brand_canonical.json` |

### `tweet_barriers`
| Column | Type | Description |
|---|---|---|
| `tweet_id` | TEXT (FK) | References `tweets.tweet_id` |
| `barrier_code` | TEXT | Consumer barrier code (e.g., `price`, `ineffective`, `side_effects`) |
| `confidence` | REAL | Model-reported confidence |

### `tweet_aspects`
| Column | Type | Description |
|---|---|---|
| `tweet_id` | TEXT (FK) | References `tweets.tweet_id` |
| `aspect` | TEXT | Grouped aspect (e.g., `scalp_health`, `sensory`, `effectiveness`) |
| `sentiment` | TEXT | Sentiment toward this aspect (`positive` / `negative` / `neutral`) |
| `span_text` | TEXT | Raw string/phrase from the tweet discussing this aspect |

---

## 5. Setup & Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/cuwipom/umm_analysis.git
   cd umm_analysis
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables:**
   Copy the environment template and insert your API credentials:
   ```bash
   cp .env.example .env
   # Open .env and add your DEEPSEEK_API_KEY and GCP configurations
   ```

---

## 6. How to Run the Pipeline

The pipeline orchestrator provides several CLI options for staged tests, caching runs, and dry-runs:

```bash
# 1. Run a 5-tweet test (estimates cost to ~$0.001)
python -m pipeline.run_pipeline --limit 5

# 2. Run a full pipeline execution (deep enrichment + embeddings generation)
python -m pipeline.run_pipeline

# 3. Re-process pipeline outputs from Cache (Zero API cost!)
# Useful when updating SQLite db structures or brand mappings without hitting DeepSeek API again
python -m pipeline.run_pipeline --skip-llm

# 4. Dry run (verify extraction and enrichments, do not save to SQLite DB)
python -m pipeline.run_pipeline --dry-run --limit 20

# 5. Skip local embedding generation
python -m pipeline.run_pipeline --skip-embeddings
```

---

## 7. Downstream SQL Analysis Examples

Once loaded into the database, running complex data evaluations is instant and free.

### A. Most Frequent Hair Loss Triggers/Causes
```sql
SELECT tc.cause_category, COUNT(DISTINCT t.tweet_id) as tweet_count
FROM tweets t
JOIN tweet_causes tc ON t.tweet_id = tc.tweet_id
GROUP BY tc.cause_category
ORDER BY tweet_count DESC;
```

### B. High-Engagement Brand Complaints
```sql
SELECT tb.brand_canonical, COUNT(t.tweet_id) as complaints_count, AVG(t.like_count) as avg_likes
FROM tweets t
JOIN tweet_brands tb ON t.tweet_id = tb.tweet_id
WHERE t.sentiment = 'negative'
GROUP BY tb.brand_canonical
HAVING complaints_count > 5
ORDER BY avg_likes DESC;
```

### C. Consumer Purchase Barriers by Product Type
```sql
SELECT tp.product_type, tbar.barrier_code, COUNT(*) as occurrence_count
FROM tweet_products tp
JOIN tweet_barriers tbar ON tp.tweet_id = tbar.tweet_id
GROUP BY tp.product_type, tbar.barrier_code
ORDER BY tp.product_type, occurrence_count DESC;
```

---

## 8. Exporting to BigQuery

If you want to sync the pipeline outputs to a centralized cloud data warehouse for dashboard visualization:

1. **Export SQLite tables to CSV exports:**
   ```bash
   python script/export_to_csv.py
   ```
   This will dump CSVs for all 6 tables in the `pipeline_output/bq_exports/` folder.

2. **Push to BigQuery dataset:**
   Make sure you are authenticated to GCP (`gcloud auth application-default login` or configure service account credentials in `.env`), then execute:
   ```bash
   python script/load_to_bq.py
   ```
