import os
import sys
import logging
from dotenv import load_dotenv
from send_report import send_daily_email_report

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("ParkLightAuditRunner")

def main():
    # Load .env
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        env_path = os.path.join(os.path.dirname(__file__), "config.env")
    load_dotenv(env_path)

    logger.info("==========================================================")
    logger.info("BBMP PARK LIGHT RELAY AUDIT DISPATCHER (ON-DEMAND)")
    logger.info("==========================================================")

    date_arg = sys.argv[1] if len(sys.argv) > 1 else "today"
    send_daily_email_report(date_arg)

if __name__ == "__main__":
    main()
