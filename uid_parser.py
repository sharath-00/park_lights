import os
import requests
import re
import csv
import logging

logger = logging.getLogger(__name__)

def fetch_light_uids_from_url(sheet_url):
    """
    Given a Google Sheets pubhtml or csv URL, extract unique UIDs,
    excluding those marked 'not in dash board'.
    """
    if not sheet_url:
        return []
        
    urls_to_fetch = []
    
    try:
        if 'pubhtml' in sheet_url:
            # It's a pubhtml link, we might need to find all sheets
            res = requests.get(sheet_url, timeout=10)
            res.raise_for_status()
            html = res.text
            # Extract all gids
            gids = re.findall(r'gid=([0-9]+)', html)
            if gids:
                # Deduplicate gids while preserving order
                unique_gids = list(dict.fromkeys(gids))
                base_csv_url = sheet_url.replace('/pubhtml', '/pub')
                for gid in unique_gids:
                    urls_to_fetch.append(f"{base_csv_url}?gid={gid}&single=true&output=csv")
            else:
                urls_to_fetch.append(sheet_url.replace('/pubhtml', '/pub?output=csv'))
        else:
            urls_to_fetch.append(sheet_url)
            
        light_uids_raw = []
        for url in urls_to_fetch:
            res = requests.get(url, timeout=10)
            res.raise_for_status()
            reader = csv.reader(res.text.strip().split('\n'))
            
            headers = next(reader, [])
            if not headers:
                continue
                
            upper_headers = [h.upper() for h in headers]
            uid_idx = upper_headers.index("UID") if "UID" in upper_headers else 0
            zone_idx = upper_headers.index("ZONE") if "ZONE" in upper_headers else -1
            
            exclude_zones = [z.strip().lower() for z in os.getenv("EXCLUDE_ZONES", "").split(",") if z.strip()]
            include_zones = [z.strip().lower() for z in os.getenv("INCLUDE_ZONES", "").split(",") if z.strip()]

            for row in reader:
                if len(row) > uid_idx and row[uid_idx].strip():
                    if zone_idx != -1 and len(row) > zone_idx:
                        zone_val = row[zone_idx].strip().lower()
                        if "not in dash" in zone_val:
                            continue
                        if exclude_zones and any(ex in zone_val for ex in exclude_zones):
                            continue
                        if include_zones and not any(inc in zone_val for inc in include_zones):
                            continue
                    light_uids_raw.append(row[uid_idx].strip())
                    
        # Remove duplicates while preserving order
        return list(dict.fromkeys(light_uids_raw))
        
    except Exception as e:
        logger.error(f"Failed to fetch or parse UIDs from Google Sheet: {e}")
        return []

def get_light_uids():
    """
    Get light UIDs from sheet URL if configured, otherwise fallback to .env list.
    """
    sheet_url = os.getenv("LIGHT_UIDS_SHEET_URL", "").strip()
    if sheet_url:
        logger.info(f"Fetching Light UIDs from Google Sheet URL: {sheet_url}")
        uids = fetch_light_uids_from_url(sheet_url)
        if uids:
            logger.info(f"Successfully loaded {len(uids)} UIDs from Google Sheet.")
            return uids
            
    env_uids = os.getenv("LIGHT_UIDS", "")
    if env_uids:
        logger.info("LIGHT_UIDS_SHEET_URL not set or failed to fetch, falling back to LIGHT_UIDS from .env")
        uids = [u.strip() for u in env_uids.split(",") if u.strip()]
        logger.info(f"Fallback to LIGHT_UIDS: loaded {len(uids)} UIDs.")
        return uids
        
    logger.warning("LIGHT_UIDS_SHEET_URL and LIGHT_UIDS are not set.")
    return []
