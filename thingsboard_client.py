import os
import logging
import requests
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

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

    def login(self) -> bool:
        """
        Authenticate with ThingsBoard API and retrieve JWT Access Token.
        """
        url = f"{self.host}/api/auth/login"
        payload = {
            "username": self.username,
            "password": self.password
        }
        headers = {"Content-Type": "application/json", "Accept": "application/json"}

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
                logger.warning(f"ThingsBoard login failed with status code {response.status_code}: {response.text}")
                return False
        except Exception as e:
            logger.warning(f"Could not connect to ThingsBoard at {self.host}: {e}")
            return False

    def get_device_id_by_name(self, device_identifier: str) -> Optional[str]:
        """
        Look up device UUID by device name or device label in ThingsBoard.
        """
        if not self.token and not self.login():
            return None

        # Check by customer deviceInfos search first (matches name & label like SSC107SM...)
        customer_id = "e2119df0-45c3-11f0-94dc-77130b2f47e9"
        url = f"{self.host}/api/customer/{customer_id}/deviceInfos"
        params = {"pageSize": 20, "page": 0, "textSearch": device_identifier}
        try:
            res = requests.get(url, headers=self.headers, params=params, timeout=10)
            if res.status_code == 200:
                data = res.json().get("data", [])
                # Exact match on label or name
                for dev in data:
                    if dev.get("label") == device_identifier or dev.get("name") == device_identifier:
                        logger.info(f"Resolved UID '{device_identifier}' -> Device Name: '{dev.get('name')}', ID: '{dev['id']['id']}'")
                        return dev["id"]["id"]
                if data:
                    dev = data[0]
                    logger.info(f"Resolved UID '{device_identifier}' via search -> Device Name: '{dev.get('name')}', ID: '{dev['id']['id']}'")
                    return dev["id"]["id"]
        except Exception as e:
            logger.debug(f"Customer device search failed for '{device_identifier}': {e}")

        # Fallback to tenant device search
        url_tenant = f"{self.host}/api/tenant/devices"
        try:
            res = requests.get(url_tenant, headers=self.headers, params={"deviceName": device_identifier}, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if "id" in data and "id" in data["id"]:
                    return data["id"]["id"]
        except Exception as e:
            logger.debug(f"Device name search failed for '{device_identifier}': {e}")
        return None

    def fetch_device_metadata(self, device_id: str) -> tuple:
        """
        Fetch Region and Zone dynamically from ThingsBoard device attributes and DeviceInfo.
        """
        region = None
        zone = None

        if not self.token:
            return None, None

        # 1. Fetch attributes from DEVICE attributes endpoint
        attr_url = f"{self.host}/api/plugins/telemetry/DEVICE/{device_id}/values/attributes"
        try:
            res = requests.get(attr_url, headers=self.headers, timeout=10)
            if res.status_code == 200:
                attrs = res.json()
                if isinstance(attrs, list):
                    attr_dict = {item.get("key"): item.get("value") for item in attrs if isinstance(item, dict)}
                    region = attr_dict.get("region") or attr_dict.get("regionName") or attr_dict.get("ownerName")
                    zone = attr_dict.get("zoneName") or attr_dict.get("zone") or attr_dict.get("wardName")
        except Exception as e:
            logger.debug(f"Attribute fetch failed for device '{device_id}': {e}")

        # 2. Fallback to DeviceInfo endpoint if attributes are missing
        if not region or not zone:
            try:
                info_url = f"{self.host}/api/device/info/{device_id}"
                res = requests.get(info_url, headers=self.headers, timeout=10)
                if res.status_code == 200:
                    info = res.json()
                    if not region:
                        region = info.get("ownerName")
                    if not zone:
                        groups = info.get("groups", [])
                        if groups and isinstance(groups, list) and len(groups) > 0:
                            zone = groups[0].get("name")
            except Exception as e:
                logger.debug(f"DeviceInfo fetch failed for device '{device_id}': {e}")

        default_region = os.getenv("DEFAULT_REGION", "Bangalore Urban")
        default_zone = os.getenv("DEFAULT_ZONE", "BBMP South Zone")
        return region or default_region, zone or default_zone

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
        """
        candidate_keys = [self.relay_key, "rly", "outputState", "ctrlState", "relayStatus", "relay_status", "status", "state", "relay", "lightState", "power", "switch"]
        
        for key in candidate_keys:
            if key in telemetry_data and telemetry_data[key]:
                entry = telemetry_data[key][0]
                raw_val = entry.get("value")
                ts = entry.get("ts")
                
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
        Provides deterministic simulation for demo/testing purposes when ThingsBoard API is unconfigured.
        """
        import time
        # Deterministically assign some lights as ON (burning) to demonstrate fault alerts
        # e.g., lights containing '02' or '04' will be ON/Burning
        is_burning = ("02" in light_uid or "04" in light_uid or "BURNING" in light_uid.upper())
        status = "ON" if is_burning else "OFF"
        
        default_region = os.getenv("DEFAULT_REGION", "Bangalore Urban")
        default_zone = os.getenv("DEFAULT_ZONE", "BBMP South Zone")
        return {
            "uid": light_uid,
            "device_id": light_uid,
            "region": default_region,
            "zone": default_zone,
            "relay_status": status,
            "raw_value": status,
            "timestamp": int(time.time() * 1000),
            "is_mock": True
        }
