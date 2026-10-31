"""
High-Speed Parallel ThingsBoard Client for 5B Innovation Park Lights Monitoring.
Authenticates via JWT and concurrently queries historical/real-time telemetry.
Uses ThreadPoolExecutor and connection pooling for sub-5-second execution.
"""
import os
import json
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from requests.adapters import HTTPAdapter

from config import Config, DATA_DIR

logger = logging.getLogger("5B_Innovation.ThingsBoard")

CACHE_FILE = DATA_DIR / "device_id_cache.json"


class ThingsBoardClient:
    def __init__(self,
                 host: Optional[str] = None,
                 username: Optional[str] = None,
                 password: Optional[str] = None,
                 customer_id: Optional[str] = None,
                 relay_key: Optional[str] = None):
        self.host = (host or Config.TB_HOST).rstrip("/")
        self.username = username or Config.TB_USERNAME
        self.password = password or Config.TB_PASSWORD
        self.customer_id = customer_id or Config.TB_CUSTOMER_ID
        self.relay_key = relay_key or Config.TELEMETRY_RELAY_KEY
        
        self.token: Optional[str] = None
        self.headers: Dict[str, str] = {}
        self._device_cache: Dict[str, str] = {}
        
        # Initialize persistent session with connection pooling
        self.session = requests.Session()
        adapter = HTTPAdapter(pool_connections=25, pool_maxsize=25, max_retries=1)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        self._load_device_cache()

    def _load_device_cache(self):
        if CACHE_FILE.exists():
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    self._device_cache = json.load(f)
                logger.info(f"Loaded {len(self._device_cache)} cached device UUIDs from {CACHE_FILE.name}")
            except Exception as e:
                logger.debug(f"Cache load error: {e}")

    def _save_device_cache(self):
        try:
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self._device_cache, f, indent=2)
        except Exception as e:
            logger.debug(f"Cache save error: {e}")

    def login(self, retries: int = 2, delay: float = 1.0) -> bool:
        """Authenticate with ThingsBoard API and obtain JWT Bearer token."""
        url = f"{self.host}/api/auth/login"
        payload = {
            "username": self.username,
            "password": self.password
        }
        headers = {"Content-Type": "application/json", "Accept": "application/json"}

        for attempt in range(1, retries + 1):
            try:
                response = self.session.post(url, json=payload, headers=headers, timeout=8)
                if response.status_code == 200:
                    data = response.json()
                    self.token = data.get("token")
                    self.headers = {
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "X-Authorization": f"Bearer {self.token}",
                        "Authorization": f"Bearer {self.token}"
                    }
                    self.session.headers.update(self.headers)
                    logger.info("Successfully authenticated with ThingsBoard API.")
                    return True
                else:
                    logger.warning(f"ThingsBoard login attempt {attempt}/{retries} failed (Status {response.status_code})")
            except Exception as e:
                logger.warning(f"ThingsBoard login connection error: {e}")

            if attempt < retries:
                time.sleep(delay)

        return False

    def resolve_device_id(self, uid: str) -> Optional[str]:
        """Resolve a single UID using cache or quick customer textSearch."""
        if uid in self._device_cache:
            return self._device_cache[uid]

        if not self.token and not self.login():
            return None

        url = f"{self.host}/api/customer/{self.customer_id}/deviceInfos"
        params = {"pageSize": 10, "page": 0, "textSearch": uid}
        try:
            res = self.session.get(url, params=params, timeout=6)
            if res.status_code == 200:
                items = res.json().get("data", [])
                for dev in items:
                    dev_id = dev.get("id", {}).get("id")
                    name = dev.get("name")
                    label = dev.get("label")
                    if uid in (name, label):
                        self._device_cache[uid] = dev_id
                        return dev_id
                if items:
                    dev_id = items[0]["id"]["id"]
                    self._device_cache[uid] = dev_id
                    return dev_id
        except Exception as e:
            logger.debug(f"Device search error for '{uid}': {e}")
        return None

    def resolve_all_device_ids(self, uids: List[str], max_workers: int = 12) -> Dict[str, str]:
        """Resolve multiple UIDs in parallel."""
        unresolved = [u for u in uids if u not in self._device_cache]
        if unresolved and self.token:
            logger.info(f"Resolving {len(unresolved)} device UUIDs via ThingsBoard in parallel...")
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(self.resolve_device_id, u): u for u in unresolved}
                for f in as_completed(futures):
                    try:
                        f.result()
                    except Exception:
                        pass
            self._save_device_cache()
        return self._device_cache

    def parse_relay_state(self, val: Any) -> str:
        """Normalize raw relay telemetry value into 'ON' or 'OFF'."""
        if val is None:
            return "UNKNOWN"
        v_str = str(val).strip().lower()
        if v_str in ("1", "true", "on", "active", "enabled"):
            return "ON"
        if v_str in ("0", "false", "off", "inactive", "disabled"):
            return "OFF"
        return "UNKNOWN"

    def fetch_panel_24h_telemetry(self,
                                  panel: Dict[str, Any],
                                  start_ts: int,
                                  end_ts: int) -> Dict[str, Any]:
        """Fetch 24-hour timeseries once for a single panel."""
        uid = panel["uid"]
        dev_id = self.resolve_device_id(uid)
        
        telemetry_points = []
        if dev_id and self.token:
            url = f"{self.host}/api/plugins/telemetry/DEVICE/{dev_id}/values/timeseries"
            params = {
                "keys": f"{self.relay_key},relayStatus,rly,outputState,ctrlState",
                "startTs": start_ts,
                "endTs": end_ts,
                "limit": 500,
                "agg": "NONE",
                "orderBy": "ASC"
            }
            try:
                res = self.session.get(url, params=params, timeout=6)
                if res.status_code == 200:
                    t_data = res.json()
                    for k in [self.relay_key, "rly", "relayStatus", "outputState", "ctrlState"]:
                        if k in t_data and t_data[k]:
                            telemetry_points = t_data[k]
                            break
            except Exception as e:
                logger.debug(f"Telemetry fetch error for {uid}: {e}")

        return {
            "uid": uid,
            "panel": panel,
            "dev_id": dev_id,
            "points": telemetry_points
        }

    def fetch_daily_4_slots_audit(self,
                                  panels: List[Dict[str, Any]],
                                  target_date_str: Optional[str] = None,
                                  max_workers: int = 15) -> Dict[str, Any]:
        """
        High-Speed Parallel 4-Slot Audit:
        Run 1: 19:00 (Yesterday 7 PM - Expected: ON)
        Run 2: 22:00 (Yesterday 10 PM - Expected: OFF)
        Run 3: 05:00 (Today 5 AM - Expected: ON)
        Run 4: 07:00 (Today 7 AM - Expected: OFF)
        """
        if not target_date_str or target_date_str.lower() == "today":
            base_date = datetime.now().date()
        elif target_date_str.lower() == "yesterday":
            base_date = datetime.now().date() - timedelta(days=1)
        else:
            base_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()

        date_str = base_date.strftime("%Y-%m-%d")
        yest_date = base_date - timedelta(days=1)

        slots_def = [
            {"slot": "19:00", "expected": "ON",  "dt": datetime.combine(yest_date, datetime.min.time()).replace(hour=19, minute=0)},
            {"slot": "22:00", "expected": "OFF", "dt": datetime.combine(yest_date, datetime.min.time()).replace(hour=22, minute=0)},
            {"slot": "05:00", "expected": "ON",  "dt": datetime.combine(base_date, datetime.min.time()).replace(hour=5, minute=0)},
            {"slot": "07:00", "expected": "OFF", "dt": datetime.combine(base_date, datetime.min.time()).replace(hour=7, minute=0)},
        ]

        # Calculate full 24h window spanning yesterday 18:30 to today 07:30
        window_start = datetime.combine(yest_date, datetime.min.time()).replace(hour=18, minute=30)
        window_end = datetime.combine(base_date, datetime.min.time()).replace(hour=7, minute=30)
        start_ts = int(window_start.timestamp() * 1000)
        end_ts = int(window_end.timestamp() * 1000)

        # Login attempt
        tb_online = self.login()
        if tb_online:
            uids = [p["uid"] for p in panels]
            self.resolve_all_device_ids(uids, max_workers=max_workers)
        else:
            logger.warning("ThingsBoard connection unavailable. Generating audit structure with simulated state.")

        # Concurrently fetch 24-hour telemetry for all panels
        panel_telemetry_map: Dict[str, List[Dict[str, Any]]] = {}
        device_ids_map: Dict[str, Optional[str]] = {}

        if tb_online:
            logger.info(f"Concurrently fetching 24-hour telemetry for {len(panels)} panels (workers={max_workers})...")
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_panel = {
                    executor.submit(self.fetch_panel_24h_telemetry, p, start_ts, end_ts): p
                    for p in panels
                }
                for f in as_completed(future_to_panel):
                    try:
                        res = f.result()
                        panel_telemetry_map[res["uid"]] = res["points"]
                        device_ids_map[res["uid"]] = res["dev_id"]
                    except Exception as e:
                        logger.debug(f"Panel telemetry error: {e}")

        # Assemble audits in RAM instantly
        audits = {}
        for s in slots_def:
            slot_name = s["slot"]
            slot_dt = s["dt"]
            exp = s["expected"]
            target_ms = int(slot_dt.timestamp() * 1000)

            lights_audit = []
            for p in panels:
                uid = p["uid"]
                pts = panel_telemetry_map.get(uid, [])
                dev_id = device_ids_map.get(uid)

                if tb_online and pts:
                    closest = min(pts, key=lambda pt: abs(pt.get("ts", 0) - target_ms))
                    relay_status = self.parse_relay_state(closest.get("value"))
                    is_mock = False
                elif tb_online:
                    relay_status = "UNKNOWN"
                    is_mock = False
                else:
                    status = exp if (hash(uid + slot_name) % 10 != 0) else ("ON" if exp == "OFF" else "OFF")
                    relay_status = status
                    is_mock = True

                is_compliant = (relay_status == exp) if relay_status != "UNKNOWN" else None

                lights_audit.append({
                    "uid": uid,
                    "panel_name": p.get("panel_name", uid),
                    "region": p.get("region", "5B Innovation"),
                    "zone": p.get("zone", "General"),
                    "device_id": dev_id,
                    "relay_status": relay_status,
                    "expected_status": exp,
                    "is_compliant": is_compliant,
                    "timestamp": slot_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "evening_slot": p.get("evening_slot", "18:00 to 21:15"),
                    "morning_slot": p.get("morning_slot", "04:00 to 06:00"),
                    "is_mock": is_mock
                })

            audits[slot_name] = {
                "timestamp": slot_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "expected": exp,
                "lights": lights_audit
            }

        return {
            "date": date_str,
            "project_name": Config.PROJECT_NAME,
            "audits": audits,
            "total_lights": len(panels)
        }
