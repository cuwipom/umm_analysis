"""
Scraper with Advanced Search Settings - Twitter/X scrapper using Scweet
Hair Treatment Consumer Barriers Research - 4 Batches
"""
import argparse
import logging
import csv
import os
import time
from datetime import datetime, timedelta
from Scweet import Scweet, RateLimitError, AuthError

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def load_tokens(filepath="config/cookies.txt"):
    """Load all auth_tokens from cookies.txt for rotation"""
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r") as f:
        return [line.strip() for line in f if line.strip()]

AUTH_TOKENS = load_tokens()
PROXY = None  # Disabled non-working proxy: http://202.129.206.239:3128

OUTPUT_DIR = "data/raw"
os.makedirs(OUTPUT_DIR, exist_ok=True)


# 🛠️ Configuration
QUERY_BASE = "Rambut Rontok"
ANY_WORDS = ["dove" ]
EXCLUDE_WORDS = ["shopee"]
LANG = "id"
DISPLAY_TYPE = "Latest"  # Options: "Top" or "Latest"

def get_search_query():
    query = QUERY_BASE
    if ANY_WORDS:
        query += f" ({' OR '.join(ANY_WORDS)})"
    if EXCLUDE_WORDS:
        query += f" {' '.join(['-' + w for w in EXCLUDE_WORDS])}"
    if LANG:
        query += f" lang:{LANG}"
    return query

# Default fallback if not provided via CLI
DEFAULT_ADVANCED_SEARCH = {
    "since": (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
    "until": datetime.now().strftime("%Y-%m-%d"),
}

RATE_LIMIT_EXIT_CODE = 2
AUTH_ERROR_EXIT_CODE = 3

def run_scrape(limit=100, since=None, until=None):
    # Set up search dates
    search_config = DEFAULT_ADVANCED_SEARCH.copy()
    if since:
        search_config["since"] = since
    if until:
        search_config["until"] = until

    print(f"\n{'='*60}")
    print(f"Running search with Account Rotation")
    print(f"Dates: {search_config['since']} to {search_config['until']}")
    print(f"Total Accounts: {len(AUTH_TOKENS)}")
    print(f"Target Limit: {limit}")
    print(f"{'='*60}\n")

    if not AUTH_TOKENS:
        print("❌ Error: No auth tokens found in cookies.txt")
        return []

    query = get_search_query()
    
    for i, token in enumerate(AUTH_TOKENS):
        print(f"👤 [Account {i+1}/{len(AUTH_TOKENS)}] Attempting with token: {token[:8]}...")
        
        scraper = Scweet(auth_token=token, proxy=PROXY)
        
        try:
            tweets = scraper.search(
                query=query,
                limit=limit,
                save=True,
                resume=False,
                display_type=DISPLAY_TYPE,
                **search_config,
            )

            if tweets:
                print(f"✓ Success! Got {len(tweets)} tweets.")
                # Clean filename from QUERY_BASE
                clean_name = QUERY_BASE.lower().replace(" ", "_").replace("\"", "")
                save_to_csv(tweets, clean_name)
                return tweets
            
            print(f"⚠️  No results with this account, trying next...")

        except (RateLimitError, AuthError, Exception) as e:
            print(f"❌ Account {i+1} failed: {e}")
            if i < len(AUTH_TOKENS) - 1:
                print("🔄 Rotating to next account...")
                continue
            else:
                print("🚫 All accounts exhausted or failed.")
    
    return []


def save_to_csv(tweets, batch_name):
    # Add a timestamp so we don't overwrite previous runs
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(OUTPUT_DIR, f"{batch_name}_{timestamp}.csv")

    if not tweets:
        return

    flat_fields = [f for f in tweets[0].keys() if f != 'user']
    user_fields = ['user_username', 'user_displayname', 'user_followers', 'user_verified']
    fieldnames = sorted(flat_fields) + user_fields

    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()

        for tweet in tweets:
            row = {k: v for k, v in tweet.items() if k != 'user'}
            user_data = tweet.get('user', {})
            row['user_username'] = user_data.get('username', '')
            row['user_displayname'] = user_data.get('displayname', '')
            row['user_followers'] = user_data.get('followers_count', 0)
            row['user_verified'] = user_data.get('verified', False)
            writer.writerow(row)

    print(f"Saved {len(tweets)} tweets to {output_file}")


def main():
    parser = argparse.ArgumentParser(description="Twitter/X Scraper - Hair Treatment Research")
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=100,
        help="Number of tweets per batch (default: 100)"
    )
    parser.add_argument(
        "--since",
        type=str,
        help="Start date for search (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--until",
        type=str,
        help="End date for search (YYYY-MM-DD)"
    )
    args = parser.parse_args()

    tweets = run_scrape(limit=args.limit, since=args.since, until=args.until)
    print(f"\n\n{'='*70}")
    print(f"SCRAPE COMPLETE")
    print(f"Total tweets: {len(tweets) if tweets else 0}")
    clean_name = QUERY_BASE.lower().replace(" ", "_").replace("\"", "")
    print(f"Output: {OUTPUT_DIR}/{clean_name}_*.csv")
    print(f"{'='*70}\n")

if __name__ == "__main__":
    main()
