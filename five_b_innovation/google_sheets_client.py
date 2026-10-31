"""
Google Sheets Client for 5B Innovation Park Lights Integration.
Fetches park lights records and UIDs using service account credentials (service.json)
with automatic fallback to published spreadsheet URLs and local cache.
"""
import os
import re
import csv
import json
import logging
from typing import Dict, List, Any, Optional
from pathlib import Path

from config import Config, BASE_DIR, DATA_DIR

logger = logging.getLogger("5B_Innovation.GoogleSheets")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly"
]


class GoogleSheetsClient:
    def __init__(self,
                 service_account_file: Optional[str] = None,
                 sheet_id_or_url: Optional[str] = None,
                 worksheet_name: Optional[str] = None):
        self.service_account_file = service_account_file or Config.SERVICE_ACCOUNT_FILE
        self.sheet_id_or_url = sheet_id_or_url or Config.GOOGLE_SHEET_ID_OR_URL
        self.worksheet_name = worksheet_name or Config.GOOGLE_WORKSHEET_NAME
        self.client = None
        self._cached_panels: List[Dict[str, Any]] = []

    def authenticate(self) -> bool:
        """
        Authenticate with Google Sheets API using service account credentials.
        Checks both GOOGLE_SERVICE_ACCOUNT_JSON environment variable and service.json file.
        """
        try:
            import gspread
            from google.oauth2.service_account import Credentials
        except ImportError:
            logger.warning("gspread or google-auth not installed. Cannot authenticate using service account.")
            return False

        # 1. Check if raw JSON string is present in environment
        env_json = Config.GOOGLE_SERVICE_ACCOUNT_JSON
        if env_json:
            try:
                info = json.loads(env_json)
                creds = Credentials.from_service_account_info(info, scopes=SCOPES)
                self.client = gspread.authorize(creds)
                logger.info("Successfully authenticated with Google Sheets via GOOGLE_SERVICE_ACCOUNT_JSON env variable.")
                return True
            except Exception as e:
                logger.warning(f"Failed to authenticate using GOOGLE_SERVICE_ACCOUNT_JSON: {e}")

        # 2. Check if service.json file exists
        service_file = Path(self.service_account_file)
        if not service_file.is_absolute():
            service_file = BASE_DIR / service_file

        if not service_file.exists():
            logger.warning(f"Service account file '{service_file}' not found.")
            return False

        try:
            creds = Credentials.from_service_account_file(str(service_file), scopes=SCOPES)
            self.client = gspread.authorize(creds)
            logger.info(f"Successfully authenticated with Google Sheets using '{service_file.name}'.")
            return True
        except Exception as e:
            logger.error(f"Error authenticating with Google Sheets API using '{service_file}': {e}")
            return False

    def fetch_from_api(self) -> Optional[List[Dict[str, Any]]]:
        """Fetch raw rows using gspread service account client."""
        if not self.sheet_id_or_url:
            logger.warning("No Google Sheet ID or URL configured.")
            return None

        # Published web URLs (/pub, /pubhtml, /d/e/2PACX-) are not Google Drive API spreadsheet IDs;
        # bypass gspread API to avoid slow failures/retries and let fetch_from_published_url handle it immediately.
        if "/d/e/2PACX-" in self.sheet_id_or_url or "/pub" in self.sheet_id_or_url:
            return None

        if not self.client and not self.authenticate():
            return None

        try:
            import gspread
            if self.sheet_id_or_url.startswith("http"):
                sheet = self.client.open_by_url(self.sheet_id_or_url)
            else:
                sheet = self.client.open_by_key(self.sheet_id_or_url)

            if self.worksheet_name:
                ws = sheet.worksheet(self.worksheet_name)
            else:
                ws = sheet.get_worksheet(0)

            records = ws.get_all_records()
            logger.info(f"Fetched {len(records)} rows from Google Sheets via API ('{sheet.title}' -> '{ws.title}')")
            return records
        except Exception as e:
            logger.warning(f"Failed to fetch from Google Sheets API via gspread: {e}")
            return None

    def fetch_from_published_url(self) -> Optional[List[Dict[str, Any]]]:
        """Fetch CSV from published Google Sheet URL."""
        if not self.sheet_id_or_url or not self.sheet_id_or_url.startswith("http"):
            return None

        try:
            import requests
            url = self.sheet_id_or_url
            if "/pubhtml" in url:
                url = url.replace("/pubhtml", "/pub?output=csv")
            elif "/edit" in url:
                url = re.sub(r'/edit.*', '/export?format=csv', url)

            res = requests.get(url, timeout=5)
            if res.status_code == 200:
                lines = res.text.strip().splitlines()
                reader = csv.DictReader(lines)
                records = list(reader)
                logger.info(f"Fetched {len(records)} rows from published Google Sheets URL via HTTP.")
                return records
            else:
                logger.warning(f"HTTP fetch returned status {res.status_code}")
                return None
        except Exception as e:
            logger.debug(f"Published URL fetch error: {e}")
            return None

    def fetch_from_local_cache(self) -> List[Dict[str, Any]]:
        """Fallback: Read from local data/5b_park_panels.csv."""
        cache_path = DATA_DIR / "5b_park_panels.csv"
        if cache_path.exists():
            try:
                with open(cache_path, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    records = list(reader)
                    logger.info(f"Loaded {len(records)} rows from local backup: {cache_path.name}")
                    return records
            except Exception as e:
                logger.error(f"Error reading local cache {cache_path}: {e}")
        return []

    def _normalize_panel_record(self, raw_row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Normalize row dictionary into standard 5B Park Light structure."""
        # Find UID key
        uid_val = None
        for k, v in raw_row.items():
            k_clean = str(k).strip().upper()
            if any(term in k_clean for term in ["VALID UID", "UID", "LIGHT UID", "DEVICE UID", "DEVICE_UID"]):
                if v and str(v).strip():
                    uid_val = str(v).strip()
                    break

        if not uid_val:
            # Fallback check first column
            first_val = list(raw_row.values())[0] if raw_row else ""
            if str(first_val).startswith(("VSC", "SSC")):
                uid_val = str(first_val).strip()

        if not uid_val or not uid_val.isalnum():
            return None

        def get_field(raw_dict, possible_names, default=""):
            for k, val in raw_dict.items():
                k_clean = str(k).strip().upper()
                if any(p.upper() == k_clean or p.upper() in k_clean for p in possible_names):
                    if val is not None and str(val).strip():
                        return str(val).strip()
            return default

        panel_name = get_field(raw_row, ["Panel Name", "Device Name", "Name", "Panel"], uid_val)
        region = get_field(raw_row, ["Region", "Circle"], "5B Innovation")
        zone = get_field(raw_row, ["Zone", "Ward", "Division"], "General Zone")
        status = get_field(raw_row, ["Status", "State"], "Online")
        version = get_field(raw_row, ["Version", "FW Version", "Firmware"], "")
        evening_slot = get_field(raw_row, ["Evening Slot", "Slot 1", "Evening"], "18:00 to 21:15")
        morning_slot = get_field(raw_row, ["Morning Slot", "Slot 2", "Morning"], "04:00 to 06:00")
        remarks = get_field(raw_row, ["Remarks", "Notes", "Remark"], "")

        return {
            "uid": uid_val,
            "panel_name": panel_name,
            "region": region,
            "zone": zone,
            "status": status,
            "version": version,
            "evening_slot": evening_slot,
            "morning_slot": morning_slot,
            "remarks": remarks,
            "raw": raw_row
        }

    def get_park_lights(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        Retrieves normalized list of 5B park light panels.
        Tries:
        1. Google Sheets API with service.json
        2. Published Sheet CSV URL
        3. Local data/5b_park_panels.csv
        """
        if self._cached_panels and not force_refresh:
            return self._cached_panels

        raw_records = self.fetch_from_api()
        if not raw_records:
            raw_records = self.fetch_from_published_url()
        if not raw_records:
            raw_records = self.fetch_from_local_cache()

        if not raw_records:
            logger.error("Failed to load park light data from Google Sheets API, published URL, or local cache.")
            return []

        panels = []
        seen_uids = set()
        for r in raw_records:
            normalized = self._normalize_panel_record(r)
            if normalized and normalized["uid"] not in seen_uids:
                seen_uids.add(normalized["uid"])
                panels.append(normalized)

        logger.info(f"Successfully processed {len(panels)} unique 5B Innovation park light panels.")
        self._cached_panels = panels
        return panels

    def get_light_uids(self) -> List[str]:
        """Returns list of light UIDs."""
        panels = self.get_park_lights()
        return [p["uid"] for p in panels]

    def get_zone_summary(self) -> Dict[str, int]:
        """Returns count of panels by zone."""
        panels = self.get_park_lights()
        zones: Dict[str, int] = {}
        for p in panels:
            z = p.get("zone") or "Unknown"
            zones[z] = zones.get(z, 0) + 1
        return zones

