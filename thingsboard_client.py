import os
import logging
import requests
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

KNOWN_UID_METADATA = {
    "SSC107SM03810": ("Bommanahali", "Bommanahali-Z1"),
    "SSC107SM03274": ("EAST", "CVRamanNagar"),
    "SSC107SM03957": ("Bommanahali", "Bommanahali-Z1"),
    "SSC107SM03860": ("Bommanahali", "Bommanahali-Z1"),
    "SSC107SM04223": ("Bommanahali", "Bommanahali-Z1"),
    "SSC107SM04278": ("Bommanahali", "Bommanahali-Z1"),
    "SSC107SM05108": ("EAST", "PulakeshiNagar"),
    "SSC107SM04796": ("EAST", "SarvagnaNagar"),
    "SSC107SM03960": ("Bommanahali", "Bommanahali-Z1"),
    "SSC107SM03828": ("Bommanahali", "Bommanahali-Z1"),
    "SSC107SM05037": ("EAST", "PulakeshiNagar"),
    "SSC107SM05145": ("EAST", "Hebbal"),
    "SSC107SM05018": ("EAST", "Hebbal"),
    "SSC107SM04263": ("Bommanahali", "Bommanahali-Z1"),
    "SSC107SM03468": ("EAST", "CVRamanNagar"),
    "SSC107SM04108": ("Bommanahali", "Bommanahali-Z1"),
    "SSC107SM05053": ("EAST", "Hebbal"),
    "SSC107SM03859": ("Bommanahali", "Bommanahali-Z1"),
    "SSC107SM05050": ("EAST", "Hebbal"),
    "SSC107SM03973": ("EAST", "PulakeshiNagar"),
    "SSC107SM02652": ("Bommanahali", "Bommanahali-Z1"),
    "SSC107SM03823": ("Bommanahali", "Bommanahali-Z1"),
    "SSC107SM05124": ("EAST", "Hebbal"),
    "SSC107SM03250": ("EAST", "CVRamanNagar"),
    "SSC107SM02850": ("Bommanahali", "Bommanahali-Z1"),
    "SSC107SM04807": ("EAST", "ShanthiNagar"),
    "SSC107SM03795": ("Bommanahali", "Bommanahali-Z1"),
    "SSC107SM04749": ("EAST", "SarvagnaNagar"),
    "SSC107SM03571": ("EAST", "CVRamanNagar"),
    "SSC107SM03744": ("EAST", "PulakeshiNagar"),
    "SSC107SM04063": ("Bommanahali", "Bommanahali-Z1"),
    "SSC107SM04621": ("EAST", "ShanthiNagar"),
    "SSC107SM03861": ("Bommanahali", "Bommanahali-Z1"),
    "SSC107SM03988": ("Bommanahali", "Bommanahali-Z1"),
    "SSC107SM03736": ("Bommanahali", "Bommanahali-Z1"),
    "SSC107SM03777": ("Bommanahali", "Bommanahali-Z1"),
    "SSC107SM03990": ("Bommanahali", "Bommanahali-Z1"),
    "SSC107SM05601": ("EAST", "CVRamanNagar")
}

class ThingsBoardClient:
    """
    ThingsBoard REST API Client for fetching relay telemetry status of park light UIDs.
    Handles JWT authentication, token refreshes, device lookup, and telemetry retrieval.
    """

    def __init__(self, host: str, username: str, password: str, relay_key: str = "relayStatus"):
        self.host = host.rstrip("/")
        self.username = username
        self.password = password
        self.relay_key = relay_key
        self.token: Optional[str] = None
        self.headers: Dict[str, str] = {}
        self._device_cache: Dict[str, str] = {}
        self._groups_cache: Dict[str, Dict[str, Any]] = {}
        self._metadata_cache: Dict[str, tuple] = {}

    def login(self, retries: int = 3, delay: float = 2.0) -> bool:
        """
        Authenticate with ThingsBoard API and retrieve JWT Access Token.
        Includes retry logic for transient 503 / 5xx server errors.
        """
        import time
        url = f"{self.host}/api/auth/login"
        payload = {
            "username": self.username,
            "password": self.password
        }
        headers = {"Content-Type": "application/json", "Accept": "application/json"}

        for attempt in range(1, retries + 1):
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    self.token = data.get("token")
                    self.headers = {
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "X-Authorization": f"Bearer {self.token}",
                        "Authorization": f"Bearer {self.token}"
                    }
                    logger.info("Successfully authenticated with ThingsBoard API.")
                    return True
                else:
                    logger.warning(f"ThingsBoard login attempt {attempt}/{retries} failed (Status {response.status_code}): {response.text[:100]}")
            except Exception as e:
                logger.warning(f"ThingsBoard login attempt {attempt}/{retries} connection error: {e}")

            if attempt < retries:
                time.sleep(delay)

        return False

    def _preload_device_cache(self):
        """
        Bulk preload device lookup maps and metadata from ThingsBoard customer deviceInfos.
        """
        if not self.token and not self.login():
            return

        customer_id = "e2119df0-45c3-11f0-94dc-77130b2f47e9"
        url = f"{self.host}/api/customer/{customer_id}/deviceInfos"
        page = 0
        loaded_count = 0
        try:
            while True:
                res = requests.get(url, headers=self.headers, params={"pageSize": 1000, "page": page}, timeout=15)
                if res.status_code != 200:
                    break
                data_page = res.json()
                items = data_page.get("data", [])
                for dev in items:
                    dev_id = dev.get("id", {}).get("id")
                    label = dev.get("label")
                    name = dev.get("name")
                    groups = [g.get("name") for g in dev.get("groups", []) if isinstance(g, dict)]
                    owner = dev.get("ownerName")

                    if dev_id:
                        self._groups_cache[dev_id] = {"groups": groups, "owner": owner, "name": name, "label": label}
                        if label:
                            self._device_cache[label] = dev_id
                        if name:
                            self._device_cache[name] = dev_id
                        loaded_count += 1

                if not data_page.get("hasNext"):
                    break
                page += 1
            logger.info(f"Preloaded {loaded_count} device definitions into ThingsBoardClient cache.")
        except Exception as e:
            logger.debug(f"Bulk device preload encountered issue: {e}")

    def get_device_id_by_name(self, device_identifier: str) -> Optional[str]:
        """
        Look up device UUID by device name or device label in ThingsBoard.
        """
        if device_identifier in self._device_cache:
            return self._device_cache[device_identifier]

        if not self.token and not self.login():
            return None

        # Try bulk preload first
        if not self._device_cache:
            self._preload_device_cache()
            if device_identifier in self._device_cache:
                return self._device_cache[device_identifier]

        # Fallback search by textSearch
        customer_id = "e2119df0-45c3-11f0-94dc-77130b2f47e9"
        url = f"{self.host}/api/customer/{customer_id}/deviceInfos"
        params = {"pageSize": 20, "page": 0, "textSearch": device_identifier}
        try:
            res = requests.get(url, headers=self.headers, params=params, timeout=10)
            if res.status_code == 200:
                data = res.json().get("data", [])
                for dev in data:
                    dev_id = dev["id"]["id"]
                    label = dev.get("label")
                    name = dev.get("name")
                    if label:
                        self._device_cache[label] = dev_id
                    if name:
                        self._device_cache[name] = dev_id
                    if label == device_identifier or name == device_identifier:
                        logger.info(f"Resolved UID '{device_identifier}' -> Device Name: '{dev.get('name')}', ID: '{dev_id}'")
                        return dev_id
                if data:
                    dev_id = data[0]["id"]["id"]
                    self._device_cache[device_identifier] = dev_id
                    return dev_id
        except Exception as e:
            logger.debug(f"Customer device search failed for '{device_identifier}': {e}")

        return None

    def fetch_device_metadata(self, device_id: str) -> tuple:
        """
        Fetch Region and Zone dynamically from ThingsBoard device attributes and DeviceInfo.
        """
        if device_id in self._metadata_cache:
            return self._metadata_cache[device_id]

        region = None
        zone = None

        if not self.token:
            return os.getenv("DEFAULT_REGION", "Bangalore Urban"), os.getenv("DEFAULT_ZONE", "BBMP South Zone")

        # 1. Fetch attributes from DEVICE attributes endpoint
        attr_url = f"{self.host}/api/plugins/telemetry/DEVICE/{device_id}/values/attributes"
        try:
            res = requests.get(attr_url, headers=self.headers, timeout=10)
            if res.status_code == 200:
                attrs = res.json()
                if isinstance(attrs, list):
                    attr_dict = {item.get("key"): item.get("value") for item in attrs if isinstance(item, dict)}
                    region = attr_dict.get("region") or attr_dict.get("regionName")
                    zone = attr_dict.get("zoneName") or attr_dict.get("zone") or attr_dict.get("wardName")
        except Exception as e:
            logger.debug(f"Attribute fetch failed for device '{device_id}': {e}")

        # 2. Check cached or fetched DeviceInfo groups if region/zone is still missing
        if not region or not zone:
            info_groups = []
            owner_name = None
            if device_id in self._groups_cache:
                info_groups = self._groups_cache[device_id].get("groups", [])
                owner_name = self._groups_cache[device_id].get("owner")
            else:
                try:
                    info_url = f"{self.host}/api/device/info/{device_id}"
                    res = requests.get(info_url, headers=self.headers, timeout=10)
                    if res.status_code == 200:
                        info = res.json()
                        owner_name = info.get("ownerName")
                        info_groups = [g.get("name") for g in info.get("groups", []) if isinstance(g, dict)]
                except Exception as e:
                    logger.debug(f"DeviceInfo fetch failed for device '{device_id}': {e}")

            if not region:
                # Find group name that represents the region (non-generic group)
                region_group = next((g for g in info_groups if g and g != "BBMP Park Light Controllers"), None)
                if region_group:
                    region = region_group
                elif owner_name and owner_name != "Bangalore (BBMP)":
                    region = owner_name

            if not zone:
                if info_groups:
                    zone = info_groups[0]

        # 3. Check static KNOWN_UID_METADATA map if region/zone is still missing
        if not region or not zone:
            if device_id in KNOWN_UID_METADATA:
                k_reg, k_zone = KNOWN_UID_METADATA[device_id]
                region = region or k_reg
                zone = zone or k_zone

        default_region = os.getenv("DEFAULT_REGION", "Bangalore Urban")
        default_zone = os.getenv("DEFAULT_ZONE", "BBMP South Zone")
        final_region = region or default_region
        final_zone = zone or default_zone

        self._metadata_cache[device_id] = (final_region, final_zone)
        return final_region, final_zone

    def fetch_light_status(self, light_uid: str) -> Dict[str, Any]:
        """
        Retrieve current relay status for a given light UID.
        Returns a dict: { "uid": light_uid, "relay_status": "ON"|"OFF"|"UNKNOWN", "timestamp": ..., "raw_value": ... }
        """
        # Attempt API fetch if authenticated or try logging in
        if not self.token:
            self.login()

        device_id = light_uid
        # If UID looks like a plain name (not UUID), attempt name lookup
        if self.token and len(light_uid) != 36:
            resolved_id = self.get_device_id_by_name(light_uid)
            if resolved_id:
                device_id = resolved_id

        region, zone = self.fetch_device_metadata(device_id)
        if (not region or region == os.getenv("DEFAULT_REGION", "Bangalore Urban")) and light_uid in KNOWN_UID_METADATA:
            region, zone = KNOWN_UID_METADATA[light_uid]

        if self.token:
            url = f"{self.host}/api/plugins/telemetry/DEVICE/{device_id}/values/timeseries"
            try:
                res = requests.get(url, headers=self.headers, timeout=10)
                if res.status_code == 200:
                    telemetry_data = res.json()
                    status, raw_val, ts = self._extract_relay_status(telemetry_data)
                    return {
                        "uid": light_uid,
                        "device_id": device_id,
                        "region": region,
                        "zone": zone,
                        "relay_status": status,
                        "raw_value": raw_val,
                        "timestamp": ts,
                        "is_mock": False
                    }
                elif res.status_code == 401:
                    # Token expired, retry login once
                    if self.login():
                        return self.fetch_light_status(light_uid)
            except Exception as e:
                logger.error(f"Error fetching telemetry for light {light_uid}: {e}")

        # Fallback / Demo handling if ThingsBoard instance is unavailable or credentials are default template
        logger.info(f"Using simulated telemetry fallback for light '{light_uid}'.")
        return self._generate_simulated_status(light_uid)

    def _extract_relay_status(self, telemetry_data: Dict[str, Any]) -> tuple:
        """
        Extract and normalize relay status from telemetry JSON dictionary.
        If telemetry timestamp is older than 6 hours (device inactive/offline), returns 'UNKNOWN'.
        """
        import time
        candidate_keys = [self.relay_key, "rly", "outputState", "ctrlState", "relayStatus", "relay_status", "status", "state", "relay", "lightState", "power", "switch"]
        
        now_ms = int(time.time() * 1000)
        # 6 hours inactivity threshold
        max_age_ms = 6 * 3600 * 1000

        for key in candidate_keys:
            if key in telemetry_data and telemetry_data[key]:
                entry = telemetry_data[key][0]
                raw_val = entry.get("value")
                ts = entry.get("ts")
                
                # Check for stale telemetry (device inactive/offline in ThingsBoard)
                if ts and isinstance(ts, (int, float)) and (now_ms - ts) > max_age_ms:
                    logger.info(f"Telemetry timestamp for key '{key}' is stale (Age: {(now_ms - ts) / 3600000:.1f} hours). Returning UNKNOWN.")
                    return "UNKNOWN", raw_val, ts

                # Normalize boolean / string status
                if isinstance(raw_val, bool):
                    norm_status = "ON" if raw_val else "OFF"
                elif isinstance(raw_val, (int, float)):
                    norm_status = "ON" if raw_val > 0 else "OFF"
                elif isinstance(raw_val, str):
                    upper_val = raw_val.strip().upper()
                    if upper_val in ["ON", "TRUE", "1", "BURNING", "HIGH", "ACTIVE"]:
                        norm_status = "ON"
                    elif upper_val in ["OFF", "FALSE", "0", "NORMAL", "LOW", "INACTIVE"]:
                        norm_status = "OFF"
                    else:
                        norm_status = upper_val
                else:
                    norm_status = "UNKNOWN"
                    
                return norm_status, raw_val, ts

        return "UNKNOWN", None, None

    def _generate_simulated_status(self, light_uid: str) -> Dict[str, Any]:
        """
        Provides deterministic simulation for demo/testing purposes when ThingsBoard API is unconfigured or returns 503.
        """
        import time
        # Deterministically assign some lights as ON (burning) to demonstrate fault alerts
        # e.g., lights containing '02' or '04' will be ON/Burning
        is_burning = ("02" in light_uid or "04" in light_uid or "BURNING" in light_uid.upper())
        status = "ON" if is_burning else "OFF"
        
        region, zone = None, None
        if light_uid in KNOWN_UID_METADATA:
            region, zone = KNOWN_UID_METADATA[light_uid]
        elif light_uid in self._metadata_cache:
            region, zone = self._metadata_cache[light_uid]

        default_region = os.getenv("DEFAULT_REGION", "Bangalore Urban")
        default_zone = os.getenv("DEFAULT_ZONE", "BBMP South Zone")
        return {
            "uid": light_uid,
            "device_id": light_uid,
            "region": region or default_region,
            "zone": zone or default_zone,
            "relay_status": status,
            "raw_value": status,
            "timestamp": int(time.time() * 1000),
            "is_mock": True
        }
