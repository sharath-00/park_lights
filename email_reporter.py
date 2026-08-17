import os
import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Base directory for logs storage
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")

class EmailReporter:
    """
    Generates rich HTML Email Dashboards and dispatches them via SMTP.
    """

    def __init__(self, smtp_host: str, smtp_port: int, smtp_user: str, smtp_pass: str,
                 sender_email: str, recipient_emails: List[str], use_tls: bool = True):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_pass = smtp_pass
        self.sender_email = sender_email
        self.recipient_emails = recipient_emails
        self.use_tls = use_tls

    def build_html_dashboard(self, current_time_slot: str, current_audit: Dict[str, Any],
                             daily_summary: Optional[Dict[str, Any]] = None) -> str:
        """
        Build a modern, responsive HTML email dashboard with shift compliance rules:
        - UID, Zone, Audit Time
        - Individual status for each of the 4 daily runs
        - Overall Status: 'Good & Efficiently Operative' (if light is ON inside timeslot & OFF outside)
          otherwise 'Not Successful'.
        """
        now_str = datetime.now().strftime("%B %d, %Y - %I:%M %p")
        default_region = os.getenv("DEFAULT_REGION", "Bangalore Urban")
        default_zone = os.getenv("DEFAULT_ZONE", "BBMP South Zone")

        audits = daily_summary.get("audits", {}) if daily_summary else {}
        
        # Standard time slots
        slot_keys = ["07:30", "09:30", "18:30", "20:30"]

        # Map each slot to its light status dict, region, and zone info
        slot_status_maps = {}
        slot_region_maps = {}
        slot_zone_maps = {}
        slot_ts_maps = {}

        # Populate maps across all available slots in audits
        all_audit_slots = set(slot_keys).union(set(audits.keys()))
        for sk in all_audit_slots:
            slot_data = audits.get(sk, {})
            lights_list = slot_data.get("lights", [])
            if lights_list:
                slot_status_maps[sk] = {l["uid"]: l.get("relay_status") for l in lights_list}
                slot_region_maps[sk] = {l["uid"]: l.get("region") for l in lights_list if l.get("region")}
                slot_zone_maps[sk] = {l["uid"]: l.get("zone") for l in lights_list if l.get("zone")}
                slot_ts_maps[sk] = {l["uid"]: l.get("timestamp") for l in lights_list}

        # Current audit light list
        curr_lights = current_audit.get("lights", [])
        for l in curr_lights:
            uid = l["uid"]
            if current_time_slot not in slot_status_maps:
                slot_status_maps[current_time_slot] = {}
                slot_region_maps[current_time_slot] = {}
                slot_zone_maps[current_time_slot] = {}
                slot_ts_maps[current_time_slot] = {}
            slot_status_maps[current_time_slot][uid] = l.get("relay_status")
            if l.get("region"):
                slot_region_maps[current_time_slot][uid] = l.get("region")
            if l.get("zone"):
                slot_zone_maps[current_time_slot][uid] = l.get("zone")
            slot_ts_maps[current_time_slot][uid] = l.get("timestamp")

        # Collect all unique light UIDs
        all_uids_set = set()
        for sk in slot_status_maps:
            all_uids_set.update(slot_status_maps[sk].keys())
        light_uids = sorted(list(all_uids_set))

        total_lights = len(light_uids)
        successful_count = 0
        unsuccessful_count = 0

        table_rows_html = ""

        # Rules:
        # 07:30 (Run 1 - Inside Morning): Expected ON
        # 09:30 (Run 2 - Outside Morning): Expected OFF
        # 18:30 (Run 3 - Inside Evening): Expected ON
        # 20:30 (Run 4 - Outside Evening): Expected OFF
        run_rules = {
            "07:30": {"expected": "ON", "name": "Run 1 (07:30 - Inside)"},
            "09:30": {"expected": "OFF", "name": "Run 2 (09:30 - Outside)"},
            "18:30": {"expected": "ON", "name": "Run 3 (18:30 - Inside)"},
            "20:30": {"expected": "OFF", "name": "Run 4 (20:30 - Outside)"}
        }

        for index, uid in enumerate(light_uids, start=1):
            # Region and Zone resolution across all recorded slots & current audit
            region_name = None
            zone_name = None
            for sk in slot_status_maps.keys():
                if not region_name and uid in slot_region_maps.get(sk, {}):
                    region_name = slot_region_maps[sk][uid]
                if not zone_name and uid in slot_zone_maps.get(sk, {}):
                    zone_name = slot_zone_maps[sk][uid]

            region_name = region_name or default_region
            zone_name = zone_name or default_zone

            # Formatted latest timestamp
            last_ts_str = now_str
            for sk in reversed(slot_keys):
                if uid in slot_ts_maps.get(sk, {}) and slot_ts_maps[sk][uid]:
                    ts_val = slot_ts_maps[sk][uid]
                    if isinstance(ts_val, (int, float)):
                        last_ts_str = datetime.fromtimestamp(ts_val / 1000.0).strftime("%I:%M %p")
                    break

            evaluations = []
            run_cells_html = ""

            for sk in slot_keys:
                st = slot_status_maps.get(sk, {}).get(uid, "N/A")
                expected_st = run_rules[sk]["expected"]

                if st == "N/A":
                    cell_badge = '<span style="color: #94a3b8; font-size: 12px;">-</span>'
                elif st == expected_st:
                    evaluations.append(True)
                    cell_badge = f'<span style="color: #16a34a; font-weight: 600; font-size: 12px;">{st} (Expected)</span>'
                else:
                    evaluations.append(False)
                    cell_badge = f'<span style="color: #dc2626; font-weight: 700; font-size: 12px;">{st} (Fault)</span>'

                run_cells_html += f'<td style="padding: 12px 10px; text-align: center;">{cell_badge}</td>'

            # Calculate overall status
            if evaluations and all(evaluations):
                overall_status_badge = '<span style="background-color: #dcfce7; color: #166534; padding: 4px 10px; border-radius: 9999px; font-weight: 700; font-size: 11px;">✅ Good & Efficiently Operative</span>'
                successful_count += 1
            else:
                overall_status_badge = '<span style="background-color: #fee2e2; color: #991b1b; padding: 4px 10px; border-radius: 9999px; font-weight: 700; font-size: 11px;">❌ Not Successful</span>'
                unsuccessful_count += 1

            bg_row = "#ffffff" if index % 2 != 0 else "#f8fafc"

            table_rows_html += f"""
            <tr style="background-color: {bg_row}; border-bottom: 1px solid #e2e8f0;">
                <td style="padding: 12px 12px; font-weight: 700; color: #0f172a; font-size: 13px;">{uid}</td>
                <td style="padding: 12px 12px; color: #475569; font-size: 12px;">{region_name}</td>
                <td style="padding: 12px 12px; color: #475569; font-size: 12px;">{zone_name}</td>
                <td style="padding: 12px 10px; text-align: center; color: #64748b; font-size: 12px;">{last_ts_str}</td>
                {run_cells_html}
                <td style="padding: 12px 12px; text-align: center;">{overall_status_badge}</td>
            </tr>
            """

        compliance_pct = round((successful_count / total_lights * 100)) if total_lights > 0 else 100

        # Alert Box HTML
        if unsuccessful_count > 0:
            alert_box_html = f"""
            <div style="background-color: #fef2f2; border-left: 4px solid #ef4444; padding: 16px; margin-bottom: 24px; border-radius: 6px;">
                <h3 style="margin: 0; color: #991b1b; font-size: 16px;">⚠️ Shift Compliance Alert: {unsuccessful_count} Light(s) Not Successful</h3>
                <p style="margin: 8px 0 0 0; color: #7f1d1d; font-size: 14px; line-height: 1.5;">
                    One or more lights failed shift compliance conditions (Must be <strong>ON inside timeslots</strong> and <strong>OFF outside timeslots</strong>).
                    Please inspect relay controls for non-compliant UIDs.
                </p>
            </div>
            """
        else:
            alert_box_html = f"""
            <div style="background-color: #f0fdf4; border-left: 4px solid #22c55e; padding: 16px; margin-bottom: 24px; border-radius: 6px;">
                <h3 style="margin: 0; color: #166534; font-size: 16px;">✅ 100% Good & Efficiently Operative</h3>
                <p style="margin: 8px 0 0 0; color: #14532d; font-size: 14px;">
                    All monitored park lights passed all 4 daily shift compliance checks (ON inside shift hours, OFF outside shift hours).
                </p>
            </div>
            """

        # Full HTML Layout
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>BBMP Park Lights Relay Shift Compliance Audit</title>
        </head>
        <body style="font-family: 'Segoe UI', Arial, sans-serif; background-color: #f1f5f9; margin: 0; padding: 20px; color: #334155;">
            <div style="max-width: 900px; margin: 0 auto; background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);">
                
                <!-- Header Banner -->
                <div style="background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); padding: 28px 24px; text-align: left; color: #ffffff;">
                    <div style="font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; color: #38bdf8; margin-bottom: 6px;">
                        BBMP Smart City Energy Management
                    </div>
                    <h1 style="margin: 0; font-size: 24px; font-weight: 700; color: #ffffff;">
                        🌳 Daily 4-Run Park Lights Shift Audit Report
                    </h1>
                    <div style="margin-top: 8px; font-size: 13px; color: #94a3b8;">
                        Report Time: {now_str} | Morning Shift (06:30-09:30 AM) & Evening Shift (05:30-08:30 PM)
                    </div>
                </div>

                <div style="padding: 24px;">
                    
                    <!-- Alert Section -->
                    {alert_box_html}

                    <!-- Stats Cards Grid -->
                    <table style="width: 100%; border-collapse: separate; border-spacing: 12px; margin-left: -12px; margin-right: -12px; margin-bottom: 20px;">
                        <tr>
                            <td style="background-color: #f8fafc; padding: 16px; border-radius: 8px; text-align: center; border: 1px solid #e2e8f0; width: 25%;">
                                <div style="font-size: 11px; text-transform: uppercase; color: #64748b; font-weight: 600;">Total Monitored</div>
                                <div style="font-size: 24px; font-weight: 700; color: #0f172a; margin-top: 4px;">{total_lights}</div>
                            </td>
                            <td style="background-color: #f0fdf4; padding: 16px; border-radius: 8px; text-align: center; border: 1px solid #bbf7d0; width: 25%;">
                                <div style="font-size: 11px; text-transform: uppercase; color: #166534; font-weight: 600;">Good & Operative</div>
                                <div style="font-size: 24px; font-weight: 700; color: #15803d; margin-top: 4px;">{successful_count}</div>
                            </td>
                            <td style="background-color: #fef2f2; padding: 16px; border-radius: 8px; text-align: center; border: 1px solid #fecaca; width: 25%;">
                                <div style="font-size: 11px; text-transform: uppercase; color: #991b1b; font-weight: 600;">Not Successful</div>
                                <div style="font-size: 24px; font-weight: 700; color: #dc2626; margin-top: 4px;">{unsuccessful_count}</div>
                            </td>
                            <td style="background-color: #f8fafc; padding: 16px; border-radius: 8px; text-align: center; border: 1px solid #e2e8f0; width: 25%;">
                                <div style="font-size: 11px; text-transform: uppercase; color: #64748b; font-weight: 600;">Compliance Rate</div>
                                <div style="font-size: 24px; font-weight: 700; color: #0284c7; margin-top: 4px;">{compliance_pct}%</div>
                            </td>
                        </tr>
                    </table>

                    <!-- Table Title -->
                    <h3 style="font-size: 16px; color: #0f172a; margin-bottom: 12px; margin-top: 24px; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px;">
                        📋 Individual 4-Run Status & Overall Shift Compliance Matrix
                    </h3>

                    <!-- Status Table -->
                    <table style="width: 100%; border-collapse: collapse; text-align: left; font-size: 13px;">
                        <thead>
                            <tr style="background-color: #e2e8f0; color: #334155; text-transform: uppercase; font-size: 11px; letter-spacing: 0.5px;">
                                <th style="padding: 10px 12px;">Light UID</th>
                                <th style="padding: 10px 12px;">Region</th>
                                <th style="padding: 10px 12px;">Zone</th>
                                <th style="padding: 10px 10px; text-align: center;">Audit Time</th>
                                <th style="padding: 10px 10px; text-align: center;">Run 1<br>(07:30 - Inside)</th>
                                <th style="padding: 10px 10px; text-align: center;">Run 2<br>(09:30 - Outside)</th>
                                <th style="padding: 10px 10px; text-align: center;">Run 3<br>(18:30 - Inside)</th>
                                <th style="padding: 10px 10px; text-align: center;">Run 4<br>(20:30 - Outside)</th>
                                <th style="padding: 10px 12px; text-align: center;">Overall Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            {table_rows_html}
                        </tbody>
                    </table>

                    <!-- Legend / Explanation Box -->
                    <div style="margin-top: 24px; background-color: #f8fafc; border: 1px solid #e2e8f0; padding: 14px; border-radius: 8px; font-size: 12px; color: #475569;">
                        <strong>Shift Compliance Logic Criteria:</strong><br>
                        • <strong>Inside Timeslots (Run 1 @ 07:30 & Run 3 @ 18:30):</strong> Relay expected <strong>ON</strong>.<br>
                        • <strong>Outside Timeslots (Run 2 @ 09:30 & Run 4 @ 20:30):</strong> Relay expected <strong>OFF</strong>.<br>
                        • <strong>Overall Status:</strong> Marked <span style="color: #15803d; font-weight: 700;">✅ Good & Efficiently Operative</span> if all shift criteria pass, else <span style="color: #dc2626; font-weight: 700;">❌ Not Successful</span>.
                    </div>

                    <!-- Footer Note -->
                    <div style="margin-top: 24px; padding-top: 16px; border-top: 1px solid #e2e8f0; font-size: 12px; color: #94a3b8; text-align: center;">
                        Automated Energy Audit System | BBMP Park Lighting Division<br>
                        This email was generated automatically by the ThingsBoard Relay Audit Scheduler.
                    </div>

                </div>
            </div>
        </body>
        </html>
        """
        return html_content

    def send_email(self, subject: str, html_body: str) -> bool:
        """
        Dispatch the HTML email to recipients via SMTP.
        """
        if not self.recipient_emails or not self.recipient_emails[0] or "example.com" in self.recipient_emails[0]:
            logger.warning("No valid recipient email address configured in SMTP settings. Skipping actual SMTP dispatch.")
            return False

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.sender_email
        msg["To"] = ", ".join(self.recipient_emails)

        msg.attach(MIMEText(html_body, "html"))

        try:
            logger.info(f"Connecting to SMTP server {self.smtp_host}:{self.smtp_port}...")
            server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=15)
            if self.use_tls:
                server.starttls()
            
            if self.smtp_user and self.smtp_pass:
                server.login(self.smtp_user, self.smtp_pass)

            server.sendmail(self.sender_email, self.recipient_emails, msg.as_string())
            server.quit()
            logger.info(f"Email successfully dispatched to {self.recipient_emails}.")
            return True
        except Exception as e:
            logger.error(f"Failed to send email via SMTP: {e}")
            return False

    def save_local_html(self, html_body: str, time_slot: str) -> str:
        """
        Saves the generated HTML dashboard locally in logs/ for offline review or testing.
        """
        os.makedirs(LOG_DIR, exist_ok=True)
        filename = f"email_report_{datetime.now().strftime('%Y%m%d')}_{time_slot.replace(':', '')}.html"
        filepath = os.path.join(LOG_DIR, filename)
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(html_body)
            logger.info(f"Saved local HTML report preview to {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"Failed to save local HTML file: {e}")
            return ""
