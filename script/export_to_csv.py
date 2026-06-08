"""
Helper script to export SQLite tables from corpus.db into CSV files 
formatted specifically for loading into Google Cloud BigQuery.
"""

import os
import sqlite3
import csv
from pathlib import Path

# Paths
DB_PATH = Path(__file__).resolve().parent.parent / "pipeline_output" / "corpus.db"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "pipeline_output" / "bq_exports"

TABLES = [
    "tweets",
    "tweet_causes",
    "tweet_products",
    "tweet_brands",
    "tweet_barriers",
    "tweet_aspects"
]

def main():
    if not DB_PATH.exists():
        print(f"Error: Database not found at {DB_PATH}. Please run the pipeline first.")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Connecting to SQLite database: {DB_PATH}")
    
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    for table in TABLES:
        output_file = OUTPUT_DIR / f"{table}.csv"
        print(f"Exporting table '{table}'...")

        try:
            # Query all data from the table
            cursor.execute(f"SELECT * FROM {table}")
            rows = cursor.fetchall()
            
            # Fetch headers
            headers = [description[0] for description in cursor.description]

            with open(output_file, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
                writer.writerow(headers)
                writer.writerows(rows)

            print(f"  ✓ Exported {len(rows)} rows to {output_file.name}")
        except Exception as e:
            print(f"  ✗ Error exporting table {table}: {e}")

    conn.close()
    print(f"\nDone! CSV exports are ready in: {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
