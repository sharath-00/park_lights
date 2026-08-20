import os
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

from thingsboard_client import ThingsBoardClient
from storage import AuditStorage
from email_reporter import EmailReporter

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("TestAuditRunner")

def normalize_time_slot(slot_str: str) -> str:
    """
    Normalizes time slot identifier. If not specified or MANUAL_CHECK/AUTO, formats current execution time (HH:MM).
    If execution time is within 20 minutes of standard shift timings (18:30, 20:30, 07:30, 09:30), aligns to standard slot.
    """
    if not slot_str or slot_str in ["AUTO", "MANUAL_CHECK"]:
        slot_str = datetime.now().strftime("%H:%M")

    standard_slots = ["18:30", "20:30", "07:30", "09:30"]
    try:
        parts = slot_str.split(":")
        run_minutes = int(parts[0]) * 60 + int(parts[1])
        for std in standard_slots:
            sp = std.split(":")
            std_minutes = int(sp[0]) * 60 + int(sp[1])
            if abs(run_minutes - std_minutes) <= 20:
                return std
    except Exception:
        pass
    return slot_str

def run_audit(time_slot: str = "AUTO", send_mail: Optional[bool] = None, custom_uids: Optional[List[str]] = None):
    """
    Executes a single audit check:
    1. Loads configuration from .env
    2. Connects to ThingsBoard & retrieves telemetry for light UIDs
    3. Persists audit snapshot in storage (on EVERY execution)
    4. Evaluates execution count: sends email on the LAST run of the day (e.g. 4th execution)
    """
    time_slot = normalize_time_slot(time_slot)
    # Load .env
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        env_path = os.path.join(os.path.dirname(__file__), "config.env")
    load_dotenv(env_path)

    # Configuration
    tb_host = os.getenv("THINGSBOARD_HOST", "https://demo.thingsboard.io")
    tb_user = os.getenv("THINGSBOARD_USERNAME", "admin@thingsboard.org")
    tb_pass = os.getenv("THINGSBOARD_PASSWORD", "admin")
    relay_key = os.getenv("TELEMETRY_RELAY_KEY", "relayStatus")
    
    if custom_uids:
        light_uids = custom_uids
    else:
        light_uids_raw = os.getenv("LIGHT_UIDS", "BBMP_PARK_LIGHT_01,BBMP_PARK_LIGHT_02,BBMP_PARK_LIGHT_03,BBMP_PARK_LIGHT_04,BBMP_PARK_LIGHT_05")
        light_uids = [u.strip() for u in light_uids_raw.split(",") if u.strip()]

    expected_daily_runs = int(os.getenv("EXPECTED_DAILY_RUNS", "4"))
    audit_timings_raw = os.getenv("AUDIT_TIMINGS", "07:30,09:30,18:30,20:30")
    configured_slots = [s.strip() for s in audit_timings_raw.split(",") if s.strip()]

    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USERNAME", "")
    smtp_pass = os.getenv("SMTP_PASSWORD", "")
    sender_email = os.getenv("SENDER_EMAIL", smtp_user or "no-reply@bbmp.gov.in")
    recipients_raw = os.getenv("RECIPIENT_EMAILS", "")
    recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]

    save_local = os.getenv("SAVE_LOCAL_HTML", "False").lower() in ["true", "1", "yes"]

    logger.info("==========================================================")
    logger.info(f"STARTING PARK LIGHT RELAY AUDIT [{time_slot}]")
    logger.info(f"Target Light UIDs: {light_uids}")
    logger.info("==========================================================")

    # Step 1: Query ThingsBoard API
    tb_client = ThingsBoardClient(host=tb_host, username=tb_user, password=tb_pass, relay_key=relay_key)
    light_results = []
    
    for uid in light_uids:
        status_info = tb_client.fetch_light_status(uid)
        light_results.append(status_info)
        logger.info(f"Light '{uid}' | Region: [{status_info.get('region')}] | Zone: [{status_info.get('zone')}] -> Relay Status: [{status_info.get('relay_status')}]")

    # Step 2: Store Audit Snapshot (ALWAYS stored on every execution)
    storage = AuditStorage()
    daily_summary = storage.record_audit(time_slot, light_results)

    audits_today = daily_summary.get("audits", {})
    audit_count = len(audits_today)

    # Auto-determine send_mail if not explicitly passed
    is_pure_mock = not tb_client.token or all(l.get("is_mock", False) for l in light_results)
    if is_pure_mock:
        logger.warning("❌ ThingsBoard server is unavailable (auth failed). Skipping email report dispatch as requested.")
        should_send_mail = False
    elif send_mail is None:
        is_configured_slot = bool(configured_slots and time_slot in configured_slots)
        is_last_configured_slot = bool(configured_slots and time_slot == configured_slots[-1])
        should_send_mail = is_configured_slot and ((audit_count >= expected_daily_runs) or is_last_configured_slot)
        logger.info(f"Daily audit execution count for today ({datetime.now().strftime('%Y-%m-%d')}): {audit_count} of {expected_daily_runs} target runs.")
        if not should_send_mail:
            logger.info(f"Data recorded for slot [{time_slot}] (Run #{audit_count}). Email report deferred until the final run (#{expected_daily_runs}).")
    else:
        should_send_mail = send_mail

    # Step 3: Build HTML Dashboard
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
        current_time_slot=time_slot,
        current_audit={"lights": light_results},
        daily_summary=daily_summary
    )

    # Step 4: Save Local HTML Preview (saved on every run if enabled)
    if save_local:
        local_path = reporter.save_local_html(html_content, time_slot)
        if local_path:
            logger.info(f"HTML Dashboard Preview generated at: {local_path}")

    # Step 5: Send Email Dashboard (only on the last run or if forced)
    if should_send_mail:
        logger.info(f"Triggering email dispatch for final run (Execution #{audit_count} of {expected_daily_runs})...")
        burning_count = sum(1 for l in light_results if l.get("relay_status") == "ON")
        subject = f"BBMP Park Lights Energy Audit ({time_slot}) - "
        subject += f"⚠️ {burning_count} Light(s) Burning Unnecessarily" if burning_count > 0 else "✅ 100% Efficiency Compliant"
        
        sent = reporter.send_email(subject, html_content)
        if sent:
            logger.info(f"Automated email report sent to {recipients}.")
            reset_after_report = os.getenv("RESET_STORAGE_AFTER_REPORT", "True").lower() in ["true", "1", "yes"]
            if reset_after_report:
                storage.clear_all_data()
                logger.info("Audit storage (data/audit_history.json) reset successfully for the next audit cycle.")
        else:
            logger.warning("Email dispatch skipped or failed (check SMTP settings in .env file). Retaining audit history in data/audit_history.json.")
    else:
        logger.info("Email dispatch skipped for this run (will be dispatched on the last run of the day).")

    logger.info("==========================================================")
    logger.info("AUDIT CHECK COMPLETED SUCCESSFULLY.")
    logger.info("==========================================================")
    return light_results

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="BBMP Park Light Audit Runner")
    parser.add_argument("time_slot", nargs="?", default="MANUAL_CHECK", help="Time slot identifier (e.g. 07:30, 09:30, 18:30, 20:30)")
    parser.add_argument("--uids", "-u", help="Comma-separated list of light UIDs to check (e.g. SSC107SM04668,SSC107SM03799)")
    parser.add_argument("--send-email", "--force-email", "--last-run", dest="force_email", action="store_true", help="Force send email report on this run")
    parser.add_argument("--no-email", dest="no_email", action="store_true", help="Force skip email report on this run")
    args = parser.parse_args()

    explicit_send = None
    if args.force_email:
        explicit_send = True
    elif args.no_email:
        explicit_send = False

    uids_list = [u.strip() for u in args.uids.split(",") if u.strip()] if args.uids else None

    run_audit(time_slot=args.time_slot, send_mail=explicit_send, custom_uids=uids_list)
