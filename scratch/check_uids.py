import os
import requests
import re
import csv
from dotenv import load_dotenv

load_dotenv('.env')
sheet_url = os.getenv('LIGHT_UIDS_SHEET_URL')

urls_to_fetch = []
if 'pubhtml' in sheet_url:
    res = requests.get(sheet_url, timeout=10)
    html = res.text
    gids = list(dict.fromkeys(re.findall(r'gid=([0-9]+)', html)))
    base_csv_url = sheet_url.replace('/pubhtml', '/pub')
    for gid in gids:
        urls_to_fetch.append(f"{base_csv_url}?gid={gid}&single=true&output=csv")

all_uids = []
zone_counts = {}

for url in urls_to_fetch:
    res = requests.get(url, timeout=10)
    reader = csv.reader(res.text.strip().split('\n'))
    headers = next(reader, [])
    if not headers: continue
    upper_headers = [h.upper() for h in headers]
    uid_idx = upper_headers.index("UID") if "UID" in upper_headers else 0
    zone_idx = upper_headers.index("ZONE") if "ZONE" in upper_headers else -1
    
    for row in reader:
        if len(row) > uid_idx and row[uid_idx].strip():
            z = row[zone_idx].strip() if zone_idx != -1 and len(row) > zone_idx else "UNKNOWN"
            zone_counts[z] = zone_counts.get(z, 0) + 1
            all_uids.append(row[uid_idx].strip())

print(f"Total UIDs in sheet: {len(all_uids)}")
print(f"Unique UIDs in sheet: {len(set(all_uids))}")
print("Zone Breakdown:")
for k, v in zone_counts.items():
    print(f" - {k}: {v}")
