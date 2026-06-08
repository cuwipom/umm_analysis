# Pipeline Implementation — Walkthrough

## What Was Built

The complete 6-stage ETL pipeline from [Architecture.md](file:///Users/barik/umarketmaker/docs/Architecture.md) is now implemented.

### Files Created (10 files)

| File | Stage | Purpose |
|---|---|---|
| [requirements.txt](file:///Users/barik/umarketmaker/requirements.txt) | — | Dependencies: pydantic, openai, sentence-transformers, numpy, tqdm |
| [pipeline/\_\_init\_\_.py](file:///Users/barik/umarketmaker/pipeline/__init__.py) | — | Package init |
| [pipeline/schema.py](file:///Users/barik/umarketmaker/pipeline/schema.py) | — | 6 enums + 8 Pydantic models (foundation for everything) |
| [pipeline/extract_clean.py](file:///Users/barik/umarketmaker/pipeline/extract_clean.py) | 1 | CSV → `CleanedTweet` (text normalization, metadata extraction, spam flagging) |
| [pipeline/cache_llm.py](file:///Users/barik/umarketmaker/pipeline/cache_llm.py) | 3 | JSON cache for LLM responses (atomic writes, load/save/get/set) |
| [pipeline/llm_enrich.py](file:///Users/barik/umarketmaker/pipeline/llm_enrich.py) | 2+3 | Per-tweet DeepSeek calls with Pydantic gate + dead-letter log |
| [pipeline/generate_embeddings.py](file:///Users/barik/umarketmaker/pipeline/generate_embeddings.py) | 4 | all-MiniLM-L6-v2 batch encoding (384-dim, local, free) |
| [pipeline/brand_normalize.py](file:///Users/barik/umarketmaker/pipeline/brand_normalize.py) | 5 | Dictionary lookup normalization |
| [pipeline/load_db.py](file:///Users/barik/umarketmaker/pipeline/load_db.py) | 6 | SQLite 6-table schema + INSERT OR REPLACE loading |
| [pipeline/run_pipeline.py](file:///Users/barik/umarketmaker/pipeline/run_pipeline.py) | All | Orchestrator with CLI flags |

### Supporting Files

| File | Purpose |
|---|---|
| [config/lookup_tables/brand_canonical.json](file:///Users/barik/umarketmaker/config/lookup_tables/brand_canonical.json) | 30-entry brand name normalization table |
| [tests/golden_set.json](file:///Users/barik/umarketmaker/tests/golden_set.json) | Placeholder for 30 manually labeled tweets |

## Verification Results

| Test | Result |
|---|---|
| Schema imports (all enums + models) | ✅ Pass |
| Stage 1: Extract 10 tweets from fix_data.csv | ✅ Pass — metadata (lang, source, views) extracted correctly |
| DB schema: 6 tables created | ✅ Pass — matches Architecture.md exactly |
| Integration: Stage 1 → mock Stage 2 → Stage 5 → Stage 6 | ✅ Pass — SQL queries from architecture work |

## How to Run

```bash
# Install dependencies
pip install -r requirements.txt

# Set your API key
export DEEPSEEK_API_KEY=your_key_here

# Test with 5 tweets (~$0.001)
python -m pipeline.run_pipeline --limit 5

# Full run (~$0.50 for 3.5k tweets)
python -m pipeline.run_pipeline

# Re-process from cache (free, after schema changes)
python -m pipeline.run_pipeline --skip-llm

# Dry run (no DB writes)
python -m pipeline.run_pipeline --dry-run --limit 50
```

## Next Steps

1. **Set `DEEPSEEK_API_KEY`** and run `python -m pipeline.run_pipeline --limit 5` to validate with real LLM responses
2. **Populate golden set** with 30 labeled tweets after validating LLM output quality
3. **Run Phase 2 test** with 50 tweets, compare against golden set
4. **Full scale run** once accuracy ≥85%
5. **Expand brand_canonical.json** after inspecting unique `brand_raw` values in the DB
