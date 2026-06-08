import os
import csv
import glob
import ast
import json

# Paths
WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_DATA_PATH = os.path.join(WORKSPACE, "data/processed/main_data.csv")
RAW_DIR = os.path.join(WORKSPACE, "data/raw")
OUTPUT_PATH = os.path.join(WORKSPACE, "data/processed/fix_data.csv")

TARGET_COLUMNS = [
    'comments', 'embedded_text', 'emojis', 'likes', 'media', 'raw', 'retweets', 
    'text', 'timestamp', 'tweet_id', 'tweet_url', 'user_username', 'user_displayname', 
    'user_followers', 'user_verified', 'user_screen_name', 'user_name', 'image_links'
]

def parse_dict_string(s):
    if not s:
        return {}
    try:
        return ast.literal_eval(s)
    except Exception:
        try:
            return json.loads(s)
        except Exception:
            return {}

def extract_metadata(row):
    raw_str = row.get("raw", "")
    raw_dict = parse_dict_string(raw_str)
    
    if raw_dict.get("__typename") == "TweetWithVisibilityResults":
        raw_dict = raw_dict.get("tweet", {})
        
    screen_name = ""
    name = ""
    
    user_results = raw_dict.get("core", {}).get("user_results", {})
    result = user_results.get("result", {})
    if result:
        core = result.get("core", {})
        if core:
            screen_name = core.get("screen_name", "")
            name = core.get("name", "")
        if not screen_name or not name:
            legacy = result.get("legacy", {})
            if legacy:
                screen_name = screen_name or legacy.get("screen_name", "")
                name = name or legacy.get("name", "")
                
    # fallback to top-level legacy if needed
    if not screen_name or not name:
        legacy = raw_dict.get("legacy", {})
        if legacy:
            user_id = legacy.get("user_id_str", "")
            # check if there is screen_name in legacy
            screen_name = screen_name or legacy.get("screen_name", "")
            name = name or legacy.get("name", "")
            
    media_str = row.get("media", "")
    media_dict = parse_dict_string(media_str)
    image_links = media_dict.get("image_links", [])
    
    return screen_name, name, image_links


def normalize_row(row):
    # Ensure all target keys exist
    normalized = {}
    for col in TARGET_COLUMNS:
        normalized[col] = row.get(col, '')

    # Try to extract screen_name, name, image_links
    extracted_screen_name, extracted_name, extracted_images = extract_metadata(normalized)
    
    # 1. user_screen_name & user_username
    if not normalized['user_screen_name']:
        if extracted_screen_name:
            normalized['user_screen_name'] = extracted_screen_name
        elif normalized['user_username']:
            normalized['user_screen_name'] = normalized['user_username']
            
    if not normalized['user_username']:
        if normalized['user_screen_name']:
            normalized['user_username'] = normalized['user_screen_name']
        elif extracted_screen_name:
            normalized['user_username'] = extracted_screen_name

    # 2. user_name & user_displayname
    if not normalized['user_name']:
        if extracted_name:
            normalized['user_name'] = extracted_name
        elif normalized['user_displayname']:
            normalized['user_name'] = normalized['user_displayname']
            
    if not normalized['user_displayname']:
        if normalized['user_name']:
            normalized['user_displayname'] = normalized['user_name']
        elif extracted_name:
            normalized['user_displayname'] = extracted_name

    # 3. image_links
    img_links_val = normalized['image_links']
    if not img_links_val or img_links_val == '[]':
        if extracted_images:
            normalized['image_links'] = json.dumps(extracted_images)
        else:
            normalized['image_links'] = '[]'
            
    return normalized

def safe_int(val):
    if not val:
        return 0
    try:
        return int(float(val))
    except ValueError:
        return 0

def main():
    print("Starting merge and deduplication process...")
    
    all_rows = []
    
    # 1. Read main_data.csv
    if os.path.exists(MAIN_DATA_PATH):
        print(f"Reading main data from {MAIN_DATA_PATH}...")
        with open(MAIN_DATA_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            main_rows_count = 0
            for row in reader:
                all_rows.append(row)
                main_rows_count += 1
        print(f"Loaded {main_rows_count} rows from main data.")
    else:
        print(f"Warning: Main data path {MAIN_DATA_PATH} does not exist.")

    # 2. Read all CSVs in raw folder
    raw_files = glob.glob(os.path.join(RAW_DIR, "*.csv"))
    print(f"Found {len(raw_files)} CSV files in raw folder: {[os.path.basename(f) for f in raw_files]}")
    
    for filepath in raw_files:
        print(f"Reading raw data from {os.path.basename(filepath)}...")
        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            raw_rows_count = 0
            for row in reader:
                all_rows.append(row)
                raw_rows_count += 1
        print(f"Loaded {raw_rows_count} rows from {os.path.basename(filepath)}.")

    print(f"Total rows before deduplication: {len(all_rows)}")

    # 3. Group and Deduplicate by tweet_id
    # We want to keep the record with the highest engagement: likes + retweets + comments
    tweets_dict = {}
    duplicated_count = 0
    
    for i, row in enumerate(all_rows):
        normalized = normalize_row(row)
        tweet_id = normalized.get('tweet_id')
        
        if not tweet_id:
            # If no tweet_id, generate a dummy or skip?
            # Twitter dataset should have tweet_id, let's keep it if text exists
            tweet_id = f"unknown_{i}"
            normalized['tweet_id'] = tweet_id

        # Calculate engagement metric
        likes = safe_int(normalized.get('likes'))
        retweets = safe_int(normalized.get('retweets'))
        comments = safe_int(normalized.get('comments'))
        engagement = likes + retweets + comments
        
        if tweet_id in tweets_dict:
            duplicated_count += 1
            # Compare engagement of current row with existing row
            existing_row = tweets_dict[tweet_id]
            existing_likes = safe_int(existing_row.get('likes'))
            existing_retweets = safe_int(existing_row.get('retweets'))
            existing_comments = safe_int(existing_row.get('comments'))
            existing_engagement = existing_likes + existing_retweets + existing_comments
            
            if engagement > existing_engagement:
                tweets_dict[tweet_id] = normalized
        else:
            tweets_dict[tweet_id] = normalized

    print(f"Deduplicated count: {duplicated_count}")
    final_rows = list(tweets_dict.values())
    print(f"Total rows after deduplication: {len(final_rows)}")

    # 4. Write to fix_data.csv
    print(f"Writing final merged and cleaned data to {OUTPUT_PATH}...")
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TARGET_COLUMNS)
        writer.writeheader()
        writer.writerows(final_rows)
        
    print("Process complete! Output saved successfully.")

if __name__ == "__main__":
    main()
