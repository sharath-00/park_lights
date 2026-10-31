"""
Excel Report Generator for 5B Innovation Park Lights Monitoring.
Creates formatted multi-sheet Excel reports with KPI summaries, zone breakdowns, and 4-slot audit matrices.
"""
import os
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from config import Config, LOGS_DIR

logger = logging.getLogger("5B_Innovation.ExcelReport")


def generate_5b_excel_report(daily_summary: Dict[str, Any],
                             panels_meta: Optional[List[Dict[str, Any]]] = None,
                             output_path: Optional[str] = None) -> str:
    """
    Generates a stylized multi-tab Excel workbook for 5B Innovation park lights.
    """
    wb = openpyxl.Workbook()
    # Remove default sheet
    wb.remove(wb.active)

    date_str = daily_summary.get("date", datetime.now().strftime("%Y-%m-%d"))
    audits = daily_summary.get("audits", {})
    # Sort chronologically by timestamp (Yesterday 19:00 -> Yesterday 22:00 -> Today 05:00 -> Today 07:00)
    slot_names = sorted(list(audits.keys()), key=lambda sk: audits.get(sk, {}).get("timestamp", ""))
    if not slot_names:
        slot_names = ["19:00", "22:00", "05:00", "07:00"]

    # Build uids map
    uids_map: Dict[str, Dict[str, Any]] = {}
    if panels_meta:
        for p in panels_meta:
            uids_map[p["uid"]] = {
                "uid": p["uid"],
                "panel_name": p.get("panel_name", p["uid"]),
                "region": p.get("region", "5B Innovation"),
                "zone": p.get("zone", "General"),
                "evening_slot": p.get("evening_slot", "18:00 to 21:15"),
                "morning_slot": p.get("morning_slot", "04:00 to 06:00"),
                "slots": {}
            }

    for slot in slot_names:
        slot_data = audits.get(slot, {})
        lights = slot_data.get("lights", [])
        for l in lights:
            uid = l["uid"]
            if uid not in uids_map:
                uids_map[uid] = {
                    "uid": uid,
                    "panel_name": l.get("panel_name", uid),
                    "region": l.get("region", "5B Innovation"),
                    "zone": l.get("zone", "General"),
                    "evening_slot": l.get("evening_slot", "18:00 to 21:15"),
                    "morning_slot": l.get("morning_slot", "04:00 to 06:00"),
                    "slots": {}
                }
            uids_map[uid]["slots"][slot] = {
                "relay_status": l.get("relay_status", "UNKNOWN"),
                "expected": l.get("expected_status", audits.get(slot, {}).get("expected", "OFF")),
                "is_compliant": l.get("is_compliant", False)
            }

    total_lights = len(uids_map)
    compliant_count = 0
    burning_count = 0
    zone_stats: Dict[str, Dict[str, int]] = {}

    for uid, info in uids_map.items():
        z = info.get("zone", "General")
        if z not in zone_stats:
            zone_stats[z] = {"total": 0, "compliant": 0, "burning": 0}
        zone_stats[z]["total"] += 1

        all_slots_compliant = True
        has_burning = False

        for slot, s_data in info["slots"].items():
            expected = s_data.get("expected")
            actual = s_data.get("relay_status")
            if expected == "OFF" and actual == "ON":
                has_burning = True
            if actual != expected and actual != "UNKNOWN":
                all_slots_compliant = False

        if has_burning:
            burning_count += 1
            zone_stats[z]["burning"] += 1

        if all_slots_compliant:
            compliant_count += 1
            zone_stats[z]["compliant"] += 1

    compliance_rate = round((compliant_count / total_lights * 100), 1) if total_lights > 0 else 0

    # Common Styles
    font_title = Font(name="Calibri", size=16, bold=True, color="1E3A8A")
    font_sub = Font(name="Calibri", size=11, italic=True, color="64748B")
    font_header = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    font_bold = Font(name="Calibri", size=11, bold=True)
    font_regular = Font(name="Calibri", size=11)
    
    fill_header = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    fill_sub_header = PatternFill(start_color="3B82F6", end_color="3B82F6", fill_type="solid")
    fill_green = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")
    fill_red = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")
    fill_blue = PatternFill(start_color="DBEAFE", end_color="DBEAFE", fill_type="solid")
    fill_gray = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
    
    border_thin = Border(
        left=Side(style="thin", color="CBD5E1"),
        right=Side(style="thin", color="CBD5E1"),
        top=Side(style="thin", color="CBD5E1"),
        bottom=Side(style="thin", color="CBD5E1")
    )

    # ==========================================
    # Sheet 1: Executive KPI Summary
    # ==========================================
    ws_kpi = wb.create_sheet(title="Executive Summary")
    ws_kpi.views.sheetView[0].showGridLines = True
    
    ws_kpi["A1"] = "5B Innovation Park Lights - Daily Energy & Relay Audit"
    ws_kpi["A1"].font = font_title
    ws_kpi["A2"] = f"Report Date: {date_str} | Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    ws_kpi["A2"].font = font_sub

    kpi_headers = ["Metric", "Value", "Status / Evaluation"]
    for col_idx, h in enumerate(kpi_headers, 1):
        cell = ws_kpi.cell(row=4, column=col_idx, value=h)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border_thin

    kpi_data = [
        ("Total Monitored Park Lights", total_lights, "Active in 5B Innovation inventory"),
        ("Fully Compliant Lights", compliant_count, "Operated on scheduled timings across all shifts"),
        ("Daytime Burning / Energy Waste", burning_count, "Relay detected ON during scheduled OFF slots" if burning_count > 0 else "Zero energy waste detected"),
        ("Overall Compliance Rate", f"{compliance_rate}%", "Excellent (≥ 95%)" if compliance_rate >= 95 else "Attention Required (< 95%)"),
        ("IoT Data Source", "ThingsBoard (https://schnelliot.in)", f"Customer ID: {Config.TB_CUSTOMER_ID}"),
        ("Inventory Data Source", "Google Sheets (via service.json)", Config.GOOGLE_SHEET_ID_OR_URL[:50] + "...")
    ]

    for row_idx, (m, v, desc) in enumerate(kpi_data, 5):
        c1 = ws_kpi.cell(row=row_idx, column=1, value=m)
        c2 = ws_kpi.cell(row=row_idx, column=2, value=v)
        c3 = ws_kpi.cell(row=row_idx, column=3, value=desc)
        for c in (c1, c2, c3):
            c.font = font_regular
            c.border = border_thin
            c.alignment = Alignment(vertical="center")
        c2.font = font_bold
        c2.alignment = Alignment(horizontal="center", vertical="center")
        if "Daytime Burning" in m and burning_count > 0:
            c2.fill = fill_red
        elif "Compliance Rate" in m:
            c2.fill = fill_green if compliance_rate >= 95 else fill_red

    # ==========================================
    # Sheet 2: Zone Breakdown
    # ==========================================
    ws_zone = wb.create_sheet(title="Zone Breakdown")
    ws_zone.views.sheetView[0].showGridLines = True
    
    ws_zone["A1"] = f"5B Innovation Park Lights - Zone Breakdown ({date_str})"
    ws_zone["A1"].font = font_title

    z_headers = ["Zone Name", "Total Panels", "Compliant Panels", "Daytime Burning Alerts", "Compliance Rate %"]
    for col_idx, h in enumerate(z_headers, 1):
        cell = ws_zone.cell(row=3, column=col_idx, value=h)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border_thin

    for row_idx, (z_name, z_d) in enumerate(sorted(zone_stats.items()), 4):
        z_rate = round(z_d["compliant"] / z_d["total"] * 100, 1) if z_d["total"] > 0 else 0
        ws_zone.cell(row=row_idx, column=1, value=z_name).alignment = Alignment(vertical="center")
        ws_zone.cell(row=row_idx, column=2, value=z_d["total"]).alignment = Alignment(horizontal="center", vertical="center")
        ws_zone.cell(row=row_idx, column=3, value=z_d["compliant"]).alignment = Alignment(horizontal="center", vertical="center")
        c_burn = ws_zone.cell(row=row_idx, column=4, value=z_d["burning"])
        c_burn.alignment = Alignment(horizontal="center", vertical="center")
        if z_d["burning"] > 0:
            c_burn.fill = fill_red
            c_burn.font = font_bold

        c_rate = ws_zone.cell(row=row_idx, column=5, value=f"{z_rate}%")
        c_rate.alignment = Alignment(horizontal="center", vertical="center")
        c_rate.font = font_bold
        c_rate.fill = fill_green if z_rate >= 90 else fill_red

        for col_i in range(1, 6):
            ws_zone.cell(row=row_idx, column=col_i).border = border_thin

    # ==========================================
    # Sheet 3: Detailed 4-Slot Light Matrix
    # ==========================================
    ws_detail = wb.create_sheet(title="Detailed Audit Matrix")
    ws_detail.views.sheetView[0].showGridLines = True
    
    ws_detail["A1"] = f"5B Innovation Park Lights - 4-Slot Audit Matrix ({date_str})"
    ws_detail["A1"].font = font_title

    d_headers = ["Light UID", "Panel Name", "Region", "Evening Slot", "Morning Slot"]
    
    def get_excel_slot_header(s_key):
        if s_key == "19:00":
            return "Yesterday 19:00 (7 PM - ON)"
        elif s_key == "22:00":
            return "Yesterday 22:00 (10 PM - OFF)"
        elif s_key == "05:00":
            return "Today 05:00 (5 AM - ON)"
        elif s_key == "07:00":
            return "Today 07:00 (7 AM - OFF)"
        return f"Run: {s_key}"

    for s in slot_names:
        d_headers.append(get_excel_slot_header(s))
    d_headers.append("Compliance Status")

    for col_idx, h in enumerate(d_headers, 1):
        cell = ws_detail.cell(row=3, column=col_idx, value=h)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border_thin

    for row_idx, (uid, info) in enumerate(sorted(uids_map.items(), key=lambda x: x[0]), 4):
        ws_detail.cell(row=row_idx, column=1, value=info["uid"]).font = Font(name="Consolas", size=10, bold=True)
        ws_detail.cell(row=row_idx, column=2, value=info["panel_name"])
        ws_detail.cell(row=row_idx, column=3, value=info["region"])
        ws_detail.cell(row=row_idx, column=4, value=info["evening_slot"])
        ws_detail.cell(row=row_idx, column=5, value=info["morning_slot"])

        col_cursor = 6
        row_compliant = True
        for s in slot_names:
            s_info = info["slots"].get(s, {})
            st = s_info.get("relay_status", "-")
            exp = s_info.get("expected", "-")
            c = ws_detail.cell(row=row_idx, column=col_cursor, value=st)
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.font = Font(name="Consolas", size=10)
            if st == "ON":
                c.fill = fill_blue
            elif st == "OFF":
                c.fill = fill_gray

            if exp in ("ON", "OFF") and st in ("ON", "OFF"):
                if exp != st:
                    row_compliant = False
                    if exp == "OFF" and st == "ON":
                        c.fill = fill_red
                        c.font = Font(name="Consolas", size=10, bold=True, color="991B1B")

            col_cursor += 1

        c_status = ws_detail.cell(row=row_idx, column=col_cursor, value="Compliant" if row_compliant else "Attention Needed")
        c_status.alignment = Alignment(horizontal="center", vertical="center")
        c_status.font = font_bold
        c_status.fill = fill_green if row_compliant else fill_red

        for col_i in range(1, col_cursor + 1):
            ws_detail.cell(row=row_idx, column=col_i).border = border_thin

    # Auto-adjust column widths for all sheets
    for ws in wb.worksheets:
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

    # Save workbook
    if not output_path:
        out_name = f"5B_Park_Lights_Audit_Report_{date_str}.xlsx"
        output_path = str(LOGS_DIR / out_name)

    wb.save(output_path)
    logger.info(f"Excel report generated successfully at: {output_path}")
    return output_path

