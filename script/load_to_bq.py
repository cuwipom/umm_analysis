"""
Helper script to load the 6 exported CSV tables directly into Google Cloud BigQuery.

Prerequisites:
  pip install google-cloud-bigquery

Usage:
  # Ensure you are authenticated with GCP:
  # gcloud auth application-default login

  # Run the script:
  python3 script/load_to_bq.py --project-id <your-gcp-project> --dataset-id <your-dataset>
"""

import argparse
import os
from pathlib import Path
from google.cloud import bigquery
from google.cloud.exceptions import NotFound

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

CSV_DIR = Path(__file__).resolve().parent.parent / "pipeline_output" / "bq_exports"
TABLES = [
    "tweets",
    "tweet_causes",
    "tweet_products",
    "tweet_brands",
    "tweet_barriers",
    "tweet_aspects"
]

def main():
    parser = argparse.ArgumentParser(description="Upload pipeline CSVs to Google Cloud BigQuery")
    parser.add_argument("--project-id", default=os.getenv("GCP_PROJECT_ID"), help="Google Cloud Project ID")
    parser.add_argument("--dataset-id", default=os.getenv("GCP_DATASET_ID"), help="BigQuery Dataset ID (e.g. hairfall_insights)")
    parser.add_argument("--credentials", default=os.getenv("GOOGLE_APPLICATION_CREDENTIALS"), help="Path to Google Cloud Service Account JSON key file")
    args = parser.parse_args()

    if not args.project_id or not args.dataset_id:
        parser.error("Google Cloud Project ID and Dataset ID are required. Please provide them via arguments (e.g., --project-id, --dataset-id) or set GCP_PROJECT_ID and GCP_DATASET_ID in your .env file.")


    if args.credentials:
        print(f"Using service account credentials from {args.credentials}")
        client = bigquery.Client.from_service_account_json(args.credentials, project=args.project_id)
    else:
        client = bigquery.Client(project=args.project_id)
    dataset_ref = bigquery.DatasetReference(args.project_id, args.dataset_id)

    # Ensure dataset exists, create if it doesn't
    try:
        client.get_dataset(dataset_ref)
        print(f"Dataset '{args.dataset_id}' found.")
    except NotFound:
        print(f"Dataset '{args.dataset_id}' not found. Creating it...")
        dataset = bigquery.Dataset(dataset_ref)
        dataset.location = "US"  # Modify if you want another region (e.g. "ASIA-SOUTHEAST2" for Jakarta)
        client.create_dataset(dataset)
        print(f"Dataset '{args.dataset_id}' created successfully.")

    # Load each CSV table
    for table_name in TABLES:
        csv_path = CSV_DIR / f"{table_name}.csv"
        if not csv_path.exists():
            print(f"Warning: CSV file not found at {csv_path}, skipping.")
            continue

        table_ref = dataset_ref.table(table_name)

        # Job configuration
        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.CSV,
            skip_leading_rows=1,      # Skip CSV header row
            autodetect=True,          # Let BigQuery detect types (STRING, INTEGER, etc.)
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE, # Overwrite if exists
        )

        print(f"Loading '{csv_path.name}' into '{args.project_id}.{args.dataset_id}.{table_name}'...")
        
        with open(csv_path, "rb") as source_file:
            load_job = client.load_table_from_file(
                source_file,
                table_ref,
                job_config=job_config
            )

        # Wait for the load job to complete
        try:
            load_job.result()
            destination_table = client.get_table(table_ref)
            print(f"  ✓ Loaded {destination_table.num_rows} rows successfully.\n")
        except Exception as e:
            print(f"  ✗ Failed to load {table_name}: {e}\n")

    print("All tables processed successfully!")

if __name__ == "__main__":
    main()
