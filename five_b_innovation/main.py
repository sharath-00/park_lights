"""
5B Innovation Park Lights Monitoring & Audit Pipeline.
Main entry point for processing Google Sheets panel records (service.json),
ThingsBoard telemetry audits, Excel export, and HTML email dashboard dispatch.
"""
import sys
import os
import argparse
import logging
from datetime import datetime
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Add current directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import Config, LOGS_DIR
from google_sheets_client import GoogleSheetsClient
from thingsboard_client import ThingsBoardClient
from storage import AuditStorage
from email_reporter import EmailReporter
from generate_excel_report import generate_5b_excel_report

logger = logging.getLogger("5B_Innovation.Main")


def run_pipeline(target_date: str = "today",
                 dry_run: bool = False,
                 generate_excel: bool = True,
                 target_uids: list = None,
                 override_recipients: list = None,
                 attach_excel: bool = True) -> bool:
    logger.info("=" * 65)
    logger.info("[START] 5B INNOVATION PARK LIGHTS MONITORING & AUDIT PIPELINE")
    logger.info(f"Target Date: {target_date} | Dry Run: {dry_run}")
    if override_recipients:
        logger.info(f"Recipient Override: {override_recipients}")
    logger.info("=" * 65)

    # 1. Fetch Panels Data from Google Sheets
    logger.info("Step 1: Reading 5B Park Lights inventory from Google Sheets...")
    sheets_client = GoogleSheetsClient()
    panels = sheets_client.get_park_lights()

    if not panels:
        logger.error("[ERROR] Failed to retrieve 5B park lights from Google Sheets or local cache. Exiting.")
        return False

    if target_uids:
        panels = [p for p in panels if p["uid"] in target_uids]
        logger.info(f"Filtered to {len(panels)} target panels based on UID list.")

    logger.info(f"[OK] Loaded {len(panels)} park light panels across {len(sheets_client.get_zone_summary())} zones.")

    # 2. Query ThingsBoard 4-Slot Telemetry
    logger.info("Step 2: Connecting to ThingsBoard for 4-slot telemetry audit...")
    tb_client = ThingsBoardClient()
    daily_summary = tb_client.fetch_daily_4_slots_audit(panels, target_date_str=target_date)

    # 3. Save to Storage
    storage = AuditStorage()
    audits = daily_summary.get("audits", {})
    for slot_name, slot_data in audits.items():
        storage.record_audit(slot_name, slot_data.get("lights", []), date_str=daily_summary.get("date"))
    logger.info(f"[OK] Recorded {len(audits)} audit slots into storage/audit_history.json")

    # 4. Generate HTML Dashboard
    logger.info("Step 3: Generating Responsive HTML Email Dashboard...")
    reporter = EmailReporter()
    html_dashboard = reporter.build_html_dashboard(daily_summary, panels_meta=panels)
    preview_file = reporter.save_local_html(html_dashboard, suffix=target_date.replace('-', ''))
    if preview_file:
        logger.info(f"[HTML] Local HTML Preview created at: {preview_file}")

    # 5. Generate Excel Report Workbook
    excel_file = None
    if generate_excel:
        logger.info("Step 4: Generating Formatted Excel Audit Workbook...")
        excel_file = generate_5b_excel_report(daily_summary, panels_meta=panels)
        logger.info(f"[EXCEL] Excel Report created at: {excel_file}")

    # 6. Send Email Notification
    if not dry_run:
        logger.info("Step 5: Dispatching Email Dashboard via SMTP...")
        # Count total unsuccessful lights across the 4 daily shift checkpoints
        all_uids = set(p["uid"] for p in panels)
        unsuccessful_uids = set()
        for s_name, s_data in audits.items():
            for l in s_data.get("lights", []):
                if l.get("relay_status") != l.get("expected_status"):
                    unsuccessful_uids.add(l["uid"])

        unsuccessful_count = len(unsuccessful_uids)
        subject = f"5B Innovation Park Lights Daily Energy Audit Report ({daily_summary.get('date')}) - "
        subject += f"⚠️ {unsuccessful_count} Light(s) Not Successful" if unsuccessful_count > 0 else "✅ 100% Good & Efficiently Operative"

        attachments = [excel_file] if (excel_file and attach_excel) else None

        sent = reporter.send_email(
            subject=subject,
            html_content=html_dashboard,
            attachment_paths=attachments,
            recipient_override=override_recipients
        )
        if sent:
            logger.info("[OK] Email Dashboard successfully dispatched.")
        else:
            logger.warning("[WARNING] Email dispatch was skipped or failed. Inspect SMTP credentials in .env.")
    else:
        logger.info("[INFO] Dry-run mode enabled: Email dispatch skipped.")

    # 7. Print Terminal Summary
    print("\n" + "=" * 65)
    print("5B INNOVATION PARK LIGHTS - AUDIT EXECUTION SUMMARY")
    print("=" * 65)
    print(f"Date:                   {daily_summary.get('date')}")
    print(f"Total Panels Monitored: {len(panels)}")
    print(f"Audit Checkpoints:      {', '.join(audits.keys())}")
    if preview_file:
        print(f"HTML Preview:           {preview_file}")
    if generate_excel and 'excel_file' in locals():
        print(f"Excel Report:           {excel_file}")
    print("=" * 65 + "\n")

    return True


def display_sheet_info():
    """Inspects and displays Google Sheets connection and parsed panels."""
    print("=" * 65)
    print("[*] INSPECTING GOOGLE SHEETS 5B PARK LIGHTS DATA")
    print("=" * 65)
    client = GoogleSheetsClient()
    panels = client.get_park_lights()
    zones = client.get_zone_summary()

    print(f"Total Unique Panels Parsed: {len(panels)}")
    print(f"Zones Identified ({len(zones)}):")
    for z, count in sorted(zones.items()):
        print(f"  - {z}: {count} panels")

    print("\nSample Panels (first 3):")
    for p in panels[:3]:
        print(f"  UID: {p['uid']:<16} | Name: {p['panel_name']:<14} | Zone: {p['zone']:<16} | Slot: {p['evening_slot']}")
    print("=" * 65)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="5B Innovation Park Lights Monitoring Pipeline")
    parser.add_argument("date", nargs="?", default="today", help="Target date YYYY-MM-DD, 'yesterday', or 'today' (default: today)")
    parser.add_argument("--date", "-d", dest="flag_date", help="Target date YYYY-MM-DD, 'yesterday', or 'today'")
    parser.add_argument("--dry-run", action="store_true", help="Generate reports without sending SMTP email")
    parser.add_argument("--no-excel", action="store_true", help="Skip Excel report generation")
    parser.add_argument("--sheet-info", "-s", action="store_true", help="Inspect and display Google Sheets inventory")
    parser.add_argument("--uids", "-u", help="Comma-separated target UIDs filter")
    parser.add_argument("--to", "-t", help="Comma-separated recipient email addresses (overrides .env RECIPIENT_EMAILS)")
    parser.add_argument("--no-attach", action="store_true", help="Do not attach Excel report to email")

    args = parser.parse_args()

    if args.sheet_info:
        display_sheet_info()
    else:
        target_d = args.flag_date or args.date
        uids_filter = [u.strip() for u in args.uids.split(",") if u.strip()] if args.uids else None
        recipients_override = [r.strip() for r in args.to.split(",") if r.strip()] if args.to else None
        run_pipeline(
            target_date=target_d,
            dry_run=args.dry_run,
            generate_excel=not args.no_excel,
            target_uids=uids_filter,
            override_recipients=recipients_override,
            attach_excel=not args.no_attach
        )
