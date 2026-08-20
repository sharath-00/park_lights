import os
import logging
from datetime import datetime
from dotenv import load_dotenv

from storage import AuditStorage
from email_reporter import EmailReporter
from thingsboard_client import ThingsBoardClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("EmailReportDispatcher")

from datetime import datetime, timedelta
from typing import Optional, List

def send_daily_email_report(date_str: Optional[str] = None, target_uids: Optional[List[str]] = None) -> bool:
    """
    Loads historical audit data for the specified date (defaulting to today or 'yesterday')
    and dispatches the consolidated HTML comparison email report.
    Optional target_uids list allows filtering report to specific light UIDs.
    """
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        env_path = os.path.join(os.path.dirname(__file__), "config.env")
    load_dotenv(env_path)

    if not date_str or date_str.lower() == "today":
        date_str = datetime.now().strftime("%Y-%m-%d")
    elif date_str.lower() == "yesterday":
        date_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USERNAME", "")
    smtp_pass = os.getenv("SMTP_PASSWORD", "")
    sender_email = os.getenv("SENDER_EMAIL", smtp_user or "no-reply@bbmp.gov.in")
    recipients_raw = os.getenv("RECIPIENT_EMAILS", "")
    recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]
    save_local = os.getenv("SAVE_LOCAL_HTML", "False").lower() in ["true", "1", "yes"]

    if not smtp_user or not smtp_pass or not recipients:
        logger.error("❌ CRITICAL: MISSING SMTP CREDENTIALS OR RECIPIENT EMAILS IN ENVIRONMENT!")
        logger.error(f"  -> SMTP_USERNAME present: {bool(smtp_user)}")
        logger.error(f"  -> SMTP_PASSWORD present: {bool(smtp_pass)}")
        logger.error(f"  -> RECIPIENT_EMAILS present: {bool(recipients)}")
        logger.error("👉 Please add SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SENDER_EMAIL, and RECIPIENT_EMAILS to GitHub Repository Secrets at: https://github.com/sharath-00/park_lights/settings/secrets/actions")

    # Configuration
    tb_host = os.getenv("THINGSBOARD_HOST", "https://demo.thingsboard.io")
    tb_user = os.getenv("THINGSBOARD_USERNAME", "admin@thingsboard.org")
    tb_pass = os.getenv("THINGSBOARD_PASSWORD", "admin")
    relay_key = os.getenv("TELEMETRY_RELAY_KEY", "rly")
    
    if target_uids:
        light_uids = target_uids
    else:
        light_uids_raw = os.getenv("LIGHT_UIDS", "")
        light_uids = [u.strip() for u in light_uids_raw.split(",") if u.strip()]

    tb_client = ThingsBoardClient(host=tb_host, username=tb_user, password=tb_pass, relay_key=relay_key)
    
    # Single-run fetch: Query historical 24h telemetry for all 4 slots directly from ThingsBoard
    logger.info("Connecting to ThingsBoard to fetch full 24-hour shift telemetry for 4 audit slots in a single run...")
    daily_summary = tb_client.fetch_daily_4_slots_telemetry(light_uids)
    
    # Save to storage for history record
    storage = AuditStorage()
    if daily_summary and daily_summary.get("audits"):
        for slot, slot_data in daily_summary["audits"].items():
            storage.record_audit(slot, slot_data.get("lights", []), date_str=daily_summary.get("date"))

    audits = daily_summary.get("audits", {}) if daily_summary else {}
    recorded_slots = sorted(list(audits.keys()))
    last_slot = recorded_slots[-1] if recorded_slots else "DAILY_SUMMARY"
    last_audit_data = audits.get(last_slot, {})

    # Check if recorded audit history contains purely synthetic mock data (e.g. complete server failure)
    is_pure_mock = all(l.get("is_mock", False) for slot_data in audits.values() for l in slot_data.get("lights", []))
    if is_pure_mock and audits:
        logger.warning("❌ Recorded audit data contains only synthetic mock entries. Skipping email dispatch.")
        return False

    logger.info("==========================================================")
    logger.info(f"GENERATING DAILY EMAIL AUDIT REPORT FOR {date_str}")
    if target_uids:
        logger.info(f"Filtered Target UIDs: {target_uids}")
    logger.info(f"Recorded Time Slots: {recorded_slots}")
    logger.info("==========================================================")

    reporter = EmailReporter(
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_user=smtp_user,
        smtp_pass=smtp_pass,
        sender_email=sender_email,
        recipient_emails=recipients,
        use_tls=True
    )

    html_content = reporter.build_html_dashboard(
        current_time_slot=last_slot,
        current_audit={"lights": last_audit_data.get("lights", [])},
        daily_summary=daily_summary
    )

    if save_local:
        local_path = reporter.save_local_html(html_content, "DAILY_REPORT")
        if local_path:
            logger.info(f"HTML Dashboard Report saved locally at: {local_path}")

    # Calculate burning count across latest audit snapshot
    latest_lights = last_audit_data.get("lights", [])
    burning_count = sum(1 for l in latest_lights if l.get("relay_status") == "ON")

    subject = f"BBMP Park Lights Daily Energy Audit Report ({date_str}) - "
    subject += f"⚠️ {burning_count} Light(s) Burning Unnecessarily" if burning_count > 0 else "✅ 100% Efficiency Compliant"

    sent = reporter.send_email(subject, html_content)
    if sent:
        logger.info(f"Daily audit email report successfully dispatched to {recipients}.")
        reset_after_report = os.getenv("RESET_STORAGE_AFTER_REPORT", "True").lower() in ["true", "1", "yes"]
        if reset_after_report:
            storage.clear_all_data()
            logger.info("Audit storage (data/audit_history.json) reset successfully for a fresh start tomorrow.")
    else:
        logger.warning("Email dispatch skipped or failed (check SMTP settings in .env file). Retaining audit history in data/audit_history.json.")

    return sent

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="BBMP Park Light Daily Email Report Dispatcher")
    parser.add_argument("date", nargs="?", default="today", help="Target date YYYY-MM-DD, 'yesterday', or 'today' (default: today)")
    parser.add_argument("--date", "-d", dest="flag_date", help="Target date YYYY-MM-DD, 'yesterday', or 'today'")
    parser.add_argument("--uids", "-u", help="Comma-separated list of target light UIDs (e.g. SSC107SM04668,SSC107SM03799)")

    args = parser.parse_args()

    target_date = args.flag_date or args.date
    uids_list = [u.strip() for u in args.uids.split(",") if u.strip()] if args.uids else None

    send_daily_email_report(target_date, target_uids=uids_list)
