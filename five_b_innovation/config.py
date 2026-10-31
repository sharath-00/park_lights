import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Base directory for the 5b_innovation package
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Try loading .env from current directory first, then fallback to parent .env
local_env = BASE_DIR / ".env"
parent_env = BASE_DIR.parent / ".env"

if local_env.exists():
    load_dotenv(dotenv_path=local_env, override=True)
elif parent_env.exists():
    load_dotenv(dotenv_path=parent_env, override=False)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("5B_Innovation.Config")


class Config:
    PROJECT_NAME = "5B Innovation Park Lights"
    
    # ThingsBoard IoT Platform
    TB_HOST = os.getenv("THINGSBOARD_HOST", "https://schnelliot.in").rstrip("/")
    TB_USERNAME = os.getenv("THINGSBOARD_USERNAME", "vinoth.joel@schnellenergy.com")
    TB_PASSWORD = os.getenv("THINGSBOARD_PASSWORD", "vinoth555")
    # 5B Innovation Customer ID in ThingsBoard (5,269 Panels)
    TB_CUSTOMER_ID = os.getenv("THINGSBOARD_CUSTOMER_ID", "3e268290-3989-11f1-9e5f-85a6074555d7")
    TELEMETRY_RELAY_KEY = os.getenv("TELEMETRY_RELAY_KEY", "rly")
    
    # Google Sheets Configuration
    SERVICE_ACCOUNT_FILE = os.getenv("SERVICE_ACCOUNT_FILE", str(BASE_DIR / "service.json"))
    GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    # Default 5B park lights spreadsheet URL
    _default_sheet_url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQIS2N_C4VqwLafeJaIvM0JLPv-Ip9XuWTEl0vsliEyF2k9C7E_tI8ypmg-QY5CcKYu8djgOdiDt_-Q/pub?gid=1923123572&single=true&output=csv"
    GOOGLE_SHEET_ID_OR_URL = os.getenv("GOOGLE_SHEET_ID_OR_URL", "").strip() or os.getenv("FIVE_B_PARK_LIGHTS_SHEET_URLS", "").strip() or _default_sheet_url
    GOOGLE_WORKSHEET_NAME = os.getenv("GOOGLE_WORKSHEET_NAME", "").strip()
    
    # Audit Schedule Timings (24-hour HH:MM format)
    # 5B Innovation slots: Evening 7 PM (19:00 - ON), Evening 10 PM (22:00 - OFF), Morning 5 AM (05:00 - ON), Morning 7 AM (07:00 - OFF)
    AUDIT_TIMINGS = os.getenv("AUDIT_TIMINGS", "19:00,22:00,05:00,07:00")
    EXPECTED_DAILY_RUNS = int(os.getenv("EXPECTED_DAILY_RUNS", "4"))
    
    # SMTP Email Configuration
    SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "True").lower() in ("true", "1", "yes")
    SMTP_USERNAME = os.getenv("SMTP_USERNAME", "vinoth.joel@schnellenergy.com")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "ufed zyzp dtlz yjlx")
    SENDER_EMAIL = os.getenv("SENDER_EMAIL", "vinoth.joel@schnellenergy.com")
    
    _recipients_str = os.getenv("RECIPIENT_EMAILS", "71762332038@cit.edu.in")
    RECIPIENT_EMAILS = [r.strip() for r in _recipients_str.split(",") if r.strip()]
    
    _bcc_str = os.getenv("BCC_EMAILS", "")
    BCC_EMAILS = [r.strip() for r in _bcc_str.split(",") if r.strip()]
    
    EMAIL_SUBJECT_PREFIX = os.getenv("EMAIL_SUBJECT_PREFIX", "[5B Innovation Park Lights Daily Audit]")
    ENABLE_EMAIL_THREADING = os.getenv("ENABLE_EMAIL_THREADING", "True").lower() in ("true", "1", "yes")
    EMAIL_THREAD_ID = os.getenv("EMAIL_THREAD_ID", "5b-innovation-park-lights-audit-thread@schnellenergy.com")
    
    SAVE_LOCAL_HTML = os.getenv("SAVE_LOCAL_HTML", "True").lower() in ("true", "1", "yes")
    RESET_STORAGE_AFTER_REPORT = os.getenv("RESET_STORAGE_AFTER_REPORT", "False").lower() in ("true", "1", "yes")

