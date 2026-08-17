import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Base directory for data storage
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
STORAGE_FILE = os.path.join(DATA_DIR, "audit_history.json")

class AuditStorage:
    """
    Manages historical persistence of light relay audit snapshots for daily checks.
    """

    def __init__(self, storage_path: str = STORAGE_FILE):
        self.storage_path = storage_path
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
        self.data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading audit history file {self.storage_path}: {e}")
        return {}

    def save(self):
        try:
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving audit history: {e}")

    def record_audit(self, time_slot: str, light_results: List[Dict[str, Any]], date_str: Optional[str] = None) -> Dict[str, Any]:
        """
        Record audit snapshot for a specific time slot (e.g. '07:30' or '09:30').
        """
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")

        if date_str not in self.data:
            self.data[date_str] = {
                "date": date_str,
                "audits": {}
            }

        # Store audit snapshot
        self.data[date_str]["audits"][time_slot] = {
            "timestamp": datetime.now().isoformat(),
            "time_slot": time_slot,
            "lights": light_results,
            "total_lights": len(light_results),
            "burning_count": sum(1 for l in light_results if l.get("relay_status") == "ON"),
            "off_count": sum(1 for l in light_results if l.get("relay_status") == "OFF")
        }

        self.save()
        logger.info(f"Recorded audit for date {date_str} at time slot {time_slot}.")
        return self.data[date_str]

    def get_daily_summary(self, date_str: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Retrieve daily audit summary containing all time slot audits for a given date.
        """
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")
        return self.data.get(date_str)
