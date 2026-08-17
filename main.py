import os
import sys
import time
import logging
from dotenv import load_dotenv
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from test_audit import run_audit

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("ParkLightSchedulerDaemon")

def scheduled_job(time_slot: str):
    logger.info(f"Triggering scheduled audit job for time slot [{time_slot}]...")
    try:
        run_audit(time_slot=time_slot, send_mail=None)
    except Exception as e:
        logger.error(f"Error during scheduled audit for {time_slot}: {e}", exc_info=True)

def main():
    # Load .env
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        env_path = os.path.join(os.path.dirname(__file__), "config.env")
    load_dotenv(env_path)

    timings_raw = os.getenv("AUDIT_TIMINGS", "07:30,09:30")
    time_slots = [t.strip() for t in timings_raw.split(",") if t.strip()]

    scheduler = BlockingScheduler()

    logger.info("==========================================================")
    logger.info("BBMP PARK LIGHT RELAY AUDIT SCHEDULER STARTED")
    logger.info(f"Configured Audit Time Slots: {time_slots}")
    logger.info("==========================================================")

    for slot in time_slots:
        try:
            parts = slot.split(":")
            hour = int(parts[0])
            minute = int(parts[1])

            scheduler.add_job(
                scheduled_job,
                trigger=CronTrigger(hour=hour, minute=minute),
                args=[slot],
                id=f"audit_job_{hour}_{minute}",
                replace_existing=True
            )
            logger.info(f"Registered daily cron job at {hour:02d}:{minute:02d} ({slot}).")
        except Exception as e:
            logger.error(f"Failed to parse time slot '{slot}': {e}")

    logger.info("Scheduler is running. Press Ctrl+C to exit.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler service stopped gracefully.")

if __name__ == "__main__":
    main()
