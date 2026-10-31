"""
Audit Storage for 5B Innovation Park Lights Monitoring.
Maintains persistent audit logs in data/audit_history.json.
"""
import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path

from config import DATA_DIR

logger = logging.getLogger("5B_Innovation.Storage")


class AuditStorage:
    def __init__(self, file_path: Optional[str] = None):
        if file_path:
            self.file_path = Path(file_path)
        else:
            self.file_path = DATA_DIR / "audit_history.json"
        self._ensure_storage_exists()

    def _ensure_storage_exists(self):
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            initial_data = {
                "created_at": datetime.now().isoformat(),
                "history": {}
            }
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(initial_data, f, indent=2)

    def load_data(self) -> Dict[str, Any]:
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading audit storage {self.file_path}: {e}")
            return {"history": {}}

    def save_data(self, data: Dict[str, Any]) -> bool:
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Error saving audit storage {self.file_path}: {e}")
            return False

    def record_audit(self, slot_name: str, lights: List[Dict[str, Any]], date_str: Optional[str] = None) -> bool:
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")

        data = self.load_data()
        history = data.setdefault("history", {})
        day_record = history.setdefault(date_str, {"audits": {}})

        day_record["audits"][slot_name] = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "lights": lights,
            "total": len(lights)
        }

        return self.save_data(data)

    def get_daily_summary(self, date_str: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")

        data = self.load_data()
        day_record = data.get("history", {}).get(date_str)
        if not day_record:
            return None

        return {
            "date": date_str,
            "audits": day_record.get("audits", {})
        }

    def clear_all_data(self) -> bool:
        initial_data = {
            "created_at": datetime.now().isoformat(),
            "history": {}
        }
        return self.save_data(initial_data)

