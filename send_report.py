import os
import logging
from datetime import datetime
from dotenv import load_dotenv

from storage import AuditStorage
from email_reporter import EmailReporter

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
    save_local = os.getenv("SAVE_LOCAL_HTML", "True").lower() in ["true", "1", "yes"]

    if not smtp_user or not smtp_pass or not recipients:
        logger.error("❌ CRITICAL: MISSING SMTP CREDENTIALS OR RECIPIENT EMAILS IN ENVIRONMENT!")
        logger.error(f"  -> SMTP_USERNAME present: {bool(smtp_user)}")
        logger.error(f"  -> SMTP_PASSWORD present: {bool(smtp_pass)}")
        logger.error(f"  -> RECIPIENT_EMAILS present: {bool(recipients)}")
        logger.error("👉 Please add SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SENDER_EMAIL, and RECIPIENT_EMAILS to GitHub Repository Secrets at: https://github.com/sharath-00/park_lights/settings/secrets/actions")

    storage = AuditStorage()
    daily_summary = storage.get_daily_summary(date_str)

    if not daily_summary or not daily_summary.get("audits"):
        all_dates = sorted(list(storage.data.keys()))
        if all_dates:
            latest_date = all_dates[-1]
            logger.info(f"No audit records found for date '{date_str}'. Falling back to latest recorded date in storage: '{latest_date}'.")
            date_str = latest_date
            daily_summary = storage.get_daily_summary(date_str)

    if not daily_summary or not daily_summary.get("audits"):
        logger.warning(f"No audit records found in storage for date {date_str}. Aborting report generation.")
        return False

    # Optional UID filtering
    if target_uids:
        filtered_audits = {}
        for slot, slot_data in daily_summary.get("audits", {}).items():
            lights = [l for l in slot_data.get("lights", []) if l.get("uid") in target_uids]
            filtered_audits[slot] = {**slot_data, "lights": lights}
        daily_summary = {**daily_summary, "audits": filtered_audits}

    audits = daily_summary.get("audits", {})
    recorded_slots = sorted(list(audits.keys()))
    last_slot = recorded_slots[-1] if recorded_slots else "DAILY_SUMMARY"
    last_audit_data = audits.get(last_slot, {})

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
    else:
        logger.info("Email dispatch skipped or failed (check SMTP settings in .env file).")
    
    reset_after_report = os.getenv("RESET_STORAGE_AFTER_REPORT", "True").lower() in ["true", "1", "yes"]
    if reset_after_report:
        storage.clear_all_data()
        logger.info("Audit storage (data/audit_history.json) reset successfully for a fresh start tomorrow.")

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
