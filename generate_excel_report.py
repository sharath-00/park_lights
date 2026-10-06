import os
import sys
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv
import requests
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from thingsboard_client import ThingsBoardClient, KNOWN_UID_METADATA

def generate_report():
    load_dotenv(".env")
    
    tb_host = os.getenv("THINGSBOARD_HOST", "https://schnelliot.in")
    tb_user = os.getenv("THINGSBOARD_USERNAME", "vinoth.joel@schnellenergy.com")
    tb_pass = os.getenv("THINGSBOARD_PASSWORD", "vinoth777")
    relay_key = os.getenv("TELEMETRY_RELAY_KEY", "rly")
    
    sheet_url = os.getenv("LIGHT_UIDS_SHEET_URL", "")
    light_uids = []
    if sheet_url:
        try:
            print(f"Fetching Light UIDs from Google Sheet: {sheet_url}")
            res = requests.get(sheet_url, timeout=10)
            res.raise_for_status()
            lines = res.text.strip().split('\n')
            for idx, line in enumerate(lines):
                if idx == 0 and "UID" in line.upper():
                    continue
                parts = line.split(',')
                if parts and parts[0].strip():
                    light_uids.append(parts[0].strip())
            print(f"Successfully loaded {len(light_uids)} UIDs from Google Sheet.")
        except Exception as e:
            print(f"Failed to fetch UIDs from Google Sheet: {e}")
            
    if not light_uids:
        light_uids_raw = os.getenv("LIGHT_UIDS", "")
        light_uids = [u.strip() for u in light_uids_raw.split(",") if u.strip()]
    
    print(f"Connecting to ThingsBoard at {tb_host}...")
    client = ThingsBoardClient(host=tb_host, username=tb_user, password=tb_pass, relay_key=relay_key)
    if not client.login():
        print("Failed to login to ThingsBoard!")
        return False
        
    client._preload_device_cache()
    
    # Start from 2026-08-21 00:00:00 to current time
    start_dt = datetime(2026, 8, 21, 0, 0, 0)
    now = datetime.now()
    end_dt = now
    start_ts = int(start_dt.timestamp() * 1000)
    end_ts = int(end_dt.timestamp() * 1000)
    
    # 4 Shift Runs per Daily Report:
    # Run 1: Previous Day 19:00 (Expected: ON)
    # Run 2: Previous Day 22:00 (Expected: OFF)
    # Run 3: Report Day 06:00 (Expected: ON)
    # Run 4: Report Day 07:00 (Expected: OFF)
    shift_definitions = [
        {"run": 1, "name": "Run 1 (Prev Evening 19:00)", "slot": "19:00", "day_offset": -1, "hour": 19, "minute": 0, "expected": "ON"},
        {"run": 2, "name": "Run 2 (Prev Night 22:00)", "slot": "22:00", "day_offset": -1, "hour": 22, "minute": 0, "expected": "OFF"},
        {"run": 3, "name": "Run 3 (Morning 06:00)", "slot": "06:00", "day_offset": 0, "hour": 6, "minute": 0, "expected": "ON"},
        {"run": 4, "name": "Run 4 (Morning 07:00)", "slot": "07:00", "day_offset": 0, "hour": 7, "minute": 0, "expected": "OFF"},
    ]
    
    # Report Dates: from Aug 22 (first complete overnight shift from Aug 21 evening) through Today (Sep 02)
    # Plus Aug 21 evening initial shift
    report_dates = []
    curr_date = datetime(2026, 8, 22).date()
    while curr_date <= end_dt.date():
        report_dates.append(curr_date)
        curr_date += timedelta(days=1)
        
    print(f"Collecting telemetry for {len(light_uids)} lights across {len(report_dates)} shift cycles (21-Aug Evening to {end_dt.strftime('%d-%b-%Y')} Morning)...")
    
    device_data = {}
    for idx, uid in enumerate(light_uids, 1):
        dev_id = client.get_device_id_by_name(uid) or uid
        if uid in KNOWN_UID_METADATA:
            region, zone = KNOWN_UID_METADATA[uid]
        else:
            region, zone = client.fetch_device_metadata(dev_id)
            
        url = f"{client.host}/api/plugins/telemetry/DEVICE/{dev_id}/values/timeseries"
        params = {
            "keys": f"{relay_key},relayStatus,ctrlState,outputState",
            "startTs": start_ts,
            "endTs": end_ts,
            "limit": 50000,
            "agg": "NONE"
        }
        entries = []
        try:
            res = requests.get(url, headers=client.headers, params=params, timeout=15)
            if res.status_code == 200:
                t_json = res.json()
                for k in [relay_key, "relayStatus", "ctrlState", "outputState"]:
                    if k in t_json and t_json[k]:
                        entries = t_json[k]
                        break
        except Exception as e:
            print(f"Error fetching for {uid}: {e}")
            
        entries.sort(key=lambda x: x["ts"])
        device_data[uid] = {
            "uid": uid,
            "dev_id": dev_id,
            "region": region or "Bangalore Urban",
            "zone": zone or "BBMP South Zone",
            "entries": entries
        }
        if idx % 10 == 0 or idx == len(light_uids):
            print(f"  Processed {idx}/{len(light_uids)} lights...")
            
    print("Telemetry collection complete! Processing overnight 24-hour shift cycles...")
    
    def evaluate_status(entries, target_dt):
        target_ms = int(target_dt.timestamp() * 1000)
        if target_dt > now:
            return "UPCOMING", None, None
            
        valid_before = [e for e in entries if e.get("ts", 0) <= target_ms + 1800000]
        if valid_before:
            best = valid_before[-1]
            raw_val = best.get("value")
            ts_val = best.get("ts")
            # Telemetry latency check (within 6 hours)
            if ts_val and abs(target_ms - ts_val) > (6 * 3600 * 1000):
                return "UNKNOWN", raw_val, ts_val
            val_str = str(raw_val).strip().upper()
            if val_str in ["1", "TRUE", "ON", "BURNING", "HIGH", "ACTIVE"]:
                return "ON", raw_val, ts_val
            elif val_str in ["0", "FALSE", "OFF", "NORMAL", "LOW", "INACTIVE"]:
                return "OFF", raw_val, ts_val
            else:
                return val_str, raw_val, ts_val
        return "NO_DATA", None, None

    master_records = []
    daily_stats = {}
    raw_slot_logs = []
    
    for r_date in report_dates:
        d_str = r_date.strftime("%Y-%m-%d")
        prev_d_str = (r_date - timedelta(days=1)).strftime("%Y-%m-%d")
        shift_label = f"{prev_d_str} Evening -> {d_str} Morning"
        
        daily_stats[d_str] = {
            "date": d_str,
            "prev_date": prev_d_str,
            "shift_label": shift_label,
            "total_lights": len(light_uids),
            "runs": {s_def["run"]: {"ON": 0, "OFF": 0, "OTHER": 0, "UPCOMING": 0} for s_def in shift_definitions},
            "compliant_count": 0,
            "non_compliant_count": 0,
            "upcoming_count": 0
        }
        
        for s_no, uid in enumerate(light_uids, 1):
            dev_info = device_data[uid]
            run_results = {}
            is_compliant = True
            has_upcoming = False
            has_evaluated = False
            
            for s_def in shift_definitions:
                r_num = s_def["run"]
                target_day = r_date + timedelta(days=s_def["day_offset"])
                slot_dt = datetime(target_day.year, target_day.month, target_day.day, s_def["hour"], s_def["minute"])
                st, raw_val, ts_val = evaluate_status(dev_info["entries"], slot_dt)
                
                run_results[r_num] = {
                    "status": st,
                    "raw_val": raw_val,
                    "ts_val": ts_val,
                    "slot_dt": slot_dt,
                    "expected": s_def["expected"],
                    "name": s_def["name"]
                }
                
                if st == "UPCOMING":
                    daily_stats[d_str]["runs"][r_num]["UPCOMING"] += 1
                    has_upcoming = True
                elif st == "ON":
                    daily_stats[d_str]["runs"][r_num]["ON"] += 1
                    has_evaluated = True
                elif st == "OFF":
                    daily_stats[d_str]["runs"][r_num]["OFF"] += 1
                    has_evaluated = True
                else:
                    daily_stats[d_str]["runs"][r_num]["OTHER"] += 1
                    has_evaluated = True
                    
                if st != "UPCOMING":
                    if st != s_def["expected"]:
                        is_compliant = False
                
                raw_slot_logs.append({
                    "report_date": d_str,
                    "shift_window": shift_label,
                    "run_number": f"Run {r_num}",
                    "run_desc": s_def["name"],
                    "scheduled_time": slot_dt.strftime("%Y-%m-%d %H:%M"),
                    "uid": uid,
                    "region": dev_info["region"],
                    "zone": dev_info["zone"],
                    "expected_status": s_def["expected"],
                    "actual_status": st,
                    "raw_value": str(raw_val) if raw_val is not None else "N/A",
                    "telemetry_timestamp": datetime.fromtimestamp(ts_val / 1000).strftime("%Y-%m-%d %H:%M:%S") if ts_val else "N/A",
                    "compliance": "PASS" if st == s_def["expected"] else ("UPCOMING" if st == "UPCOMING" else "FAIL")
                })
                
            if not has_evaluated and has_upcoming:
                overall_status = "Upcoming Shift"
                daily_stats[d_str]["upcoming_count"] += 1
            elif is_compliant:
                overall_status = "Good & Efficiently Operative"
                daily_stats[d_str]["compliant_count"] += 1
            else:
                overall_status = "Non-Compliant / Action Needed"
                daily_stats[d_str]["non_compliant_count"] += 1
                
            master_records.append({
                "report_date": d_str,
                "shift_window": shift_label,
                "s_no": s_no,
                "uid": uid,
                "region": dev_info["region"],
                "zone": dev_info["zone"],
                "run1": run_results[1]["status"],
                "run2": run_results[2]["status"],
                "run3": run_results[3]["status"],
                "run4": run_results[4]["status"],
                "overall_status": overall_status,
                "remarks": "100% Shift Compliant (ON & OFF cycles matched)" if overall_status == "Good & Efficiently Operative" else ("Upcoming audit slots pending" if overall_status == "Upcoming Shift" else "Deviation from planned ON/OFF schedule")
            })

    print("Building professional Excel workbook with overnight shift mapping...")
    
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    
    # ------------------ STYLES ------------------
    header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    sub_header_fill = PatternFill(start_color="2F5597", end_color="2F5597", fill_type="solid")
    section_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
    accent_kpi_fill = PatternFill(start_color="EAECEE", end_color="EAECEE", fill_type="solid")
    
    font_title = Font(name="Calibri", size=16, bold=True, color="1F4E78")
    font_subtitle = Font(name="Calibri", size=11, italic=True, color="595959")
    font_header = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    font_sub_header = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
    font_section = Font(name="Calibri", size=11, bold=True, color="1F4E78")
    font_bold = Font(name="Calibri", size=10, bold=True)
    font_regular = Font(name="Calibri", size=10)
    
    fill_on_good = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
    font_on_good = Font(name="Calibri", size=10, bold=True, color="375623")
    
    fill_off_good = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
    font_off_good = Font(name="Calibri", size=10, bold=True, color="375623")
    
    fill_on_bad = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")
    font_on_bad = Font(name="Calibri", size=10, bold=True, color="C65911")
    
    fill_off_bad = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")
    font_off_bad = Font(name="Calibri", size=10, bold=True, color="C65911")
    
    fill_upcoming = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")
    font_upcoming = Font(name="Calibri", size=10, italic=True, color="7F7F7F")
    
    fill_unknown = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
    font_unknown = Font(name="Calibri", size=10, bold=True, color="7F6000")
    
    fill_badge_good = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    font_badge_good = Font(name="Calibri", size=10, bold=True, color="006100")
    
    fill_badge_bad = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
    font_badge_bad = Font(name="Calibri", size=10, bold=True, color="9C0006")
    
    fill_badge_pending = PatternFill(start_color="EDEDED", end_color="EDEDED", fill_type="solid")
    font_badge_pending = Font(name="Calibri", size=10, italic=True, color="595959")

    thin_border_side = Side(border_style="thin", color="D9D9D9")
    grid_border = Border(left=thin_border_side, right=thin_border_side, top=thin_border_side, bottom=thin_border_side)
    
    # ------------------ SHEET 1: EXECUTIVE SUMMARY ------------------
    ws_sum = wb.create_sheet(title="Executive Summary")
    ws_sum.views.sheetView[0].showGridLines = True
    
    ws_sum["A1"] = "BBMP PARK LIGHTS - OVERNIGHT SHIFT AUDIT REPORT"
    ws_sum["A1"].font = font_title
    ws_sum["A2"] = f"24-Hour Shift Cycle (Yesterday 19:00 & 22:00 + Today 06:00 & 07:00) | Period: 21-Aug to {end_dt.strftime('%d-%b-%Y')} | Generated: {now.strftime('%Y-%m-%d %H:%M:%S')}"
    ws_sum["A2"].font = font_subtitle
    
    # KPI Box
    ws_sum["A4"] = "OPERATIONAL SHIFT HIGHLIGHTS"
    ws_sum["A4"].font = font_section
    ws_sum["A4"].fill = section_fill
    ws_sum.merge_cells("A4:H4")
    
    kpis = [
        ("Total Monitored Lights", str(len(light_uids))),
        ("Reporting Shift Span", f"{len(report_dates)} Daily Shifts (Aug 21 Night to Sep 02 Morning)"),
        ("Shift Cycle Standard", "Run 1 (Prev 19:00 ON) | Run 2 (Prev 22:00 OFF) | Run 3 (06:00 ON) | Run 4 (07:00 OFF)"),
        ("Total Evaluated Slots", f"{len(master_records) * 4:,} Checks")
    ]
    for k_idx, (kpi_label, kpi_val) in enumerate(kpis):
        col_start = 1 + (k_idx * 2)
        c1 = ws_sum.cell(row=5, column=col_start, value=kpi_label)
        c2 = ws_sum.cell(row=6, column=col_start, value=kpi_val)
        c1.font = Font(name="Calibri", size=9, bold=True, color="595959")
        c2.font = Font(name="Calibri", size=12, bold=True, color="1F4E78")
        c1.alignment = Alignment(horizontal="center", vertical="center")
        c2.alignment = Alignment(horizontal="center", vertical="center")
        ws_sum.merge_cells(start_row=5, start_column=col_start, end_row=5, end_column=col_start+1)
        ws_sum.merge_cells(start_row=6, start_column=col_start, end_row=6, end_column=col_start+1)
        for r in range(5, 7):
            for c in range(col_start, col_start+2):
                ws_sum.cell(row=r, column=c).fill = accent_kpi_fill
                ws_sum.cell(row=r, column=c).border = grid_border

    # Shift Performance Summary Table
    ws_sum["A8"] = "DAILY SHIFT COMPLIANCE SUMMARY (YESTERDAY EVENING + TODAY MORNING)"
    ws_sum["A8"].font = font_section
    ws_sum["A8"].fill = section_fill
    ws_sum.merge_cells("A8:K8")
    
    sum_headers = [
        "Daily Report Date", "Shift Window", "Total Lights",
        "Run 1 (Prev 19:00)\nExp: ON", "Run 2 (Prev 22:00)\nExp: OFF",
        "Run 3 (Today 06:00)\nExp: ON", "Run 4 (Today 07:00)\nExp: OFF",
        "100% Compliant", "Non-Compliant", "Compliance %", "Shift Health"
    ]
    for c_idx, h in enumerate(sum_headers, 1):
        cell = ws_sum.cell(row=9, column=c_idx, value=h)
        cell.font = font_header
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = grid_border
    ws_sum.row_dimensions[9].height = 28
    
    row_idx = 10
    for d_str in sorted(daily_stats.keys()):
        stat = daily_stats[d_str]
        r1_txt = f"ON: {stat['runs'][1]['ON']} | OFF: {stat['runs'][1]['OFF']}" if stat['runs'][1]['UPCOMING'] == 0 else "Upcoming"
        r2_txt = f"ON: {stat['runs'][2]['ON']} | OFF: {stat['runs'][2]['OFF']}" if stat['runs'][2]['UPCOMING'] == 0 else "Upcoming"
        r3_txt = f"ON: {stat['runs'][3]['ON']} | OFF: {stat['runs'][3]['OFF']}" if stat['runs'][3]['UPCOMING'] == 0 else "Upcoming"
        r4_txt = f"ON: {stat['runs'][4]['ON']} | OFF: {stat['runs'][4]['OFF']}" if stat['runs'][4]['UPCOMING'] == 0 else "Upcoming"
        
        evaluated_in_day = stat["compliant_count"] + stat["non_compliant_count"]
        comp_rate = (stat["compliant_count"] / evaluated_in_day * 100) if evaluated_in_day > 0 else 0
        
        if evaluated_in_day == 0:
            health = "Pending Run"
            h_fill = fill_badge_pending
            h_font = font_badge_pending
        elif comp_rate >= 80:
            health = "Excellent"
            h_fill = fill_badge_good
            h_font = font_badge_good
        elif comp_rate >= 50:
            health = "Moderate"
            h_fill = fill_unknown
            h_font = font_unknown
        else:
            health = "Needs Attention"
            h_fill = fill_badge_bad
            h_font = font_badge_bad
            
        row_vals = [
            d_str, stat["shift_label"], stat["total_lights"],
            r1_txt, r2_txt, r3_txt, r4_txt,
            stat["compliant_count"], stat["non_compliant_count"],
            f"{comp_rate:.1f}%" if evaluated_in_day > 0 else "N/A",
            health
        ]
        
        for c_idx, val in enumerate(row_vals, 1):
            cell = ws_sum.cell(row=row_idx, column=c_idx, value=val)
            cell.font = font_regular
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = grid_border
            if c_idx == 11:
                cell.fill = h_fill
                cell.font = h_font
                
        row_idx += 1
        
    # Zone Breakdown
    row_idx += 2
    ws_sum.cell(row=row_idx, column=1, value="ZONE & SUB-DIVISION DISTRIBUTION").font = font_section
    ws_sum.cell(row=row_idx, column=1).fill = section_fill
    ws_sum.merge_cells(start_row=row_idx, start_column=1, end_row=row_idx, end_column=5)
    row_idx += 1
    
    zone_headers = ["Zone / Sub-Division", "Region", "Total Lights Monitored", "Share %", "Status Summary"]
    for c_idx, h in enumerate(zone_headers, 1):
        cell = ws_sum.cell(row=row_idx, column=c_idx, value=h)
        cell.font = font_sub_header
        cell.fill = sub_header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = grid_border
    row_idx += 1
    
    zone_counts = {}
    for uid in light_uids:
        info = device_data[uid]
        key = (info["zone"], info["region"])
        zone_counts[key] = zone_counts.get(key, 0) + 1
        
    for (z_name, r_name), cnt in sorted(zone_counts.items(), key=lambda x: x[1], reverse=True):
        share = cnt / len(light_uids) * 100
        row_vals = [z_name, r_name, cnt, f"{share:.1f}%", "Active in Audit"]
        for c_idx, val in enumerate(row_vals, 1):
            cell = ws_sum.cell(row=row_idx, column=c_idx, value=val)
            cell.font = font_regular
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = grid_border
        row_idx += 1

    # ------------------ SHEET 2: CONSOLIDATED DAILY AUDITS ------------------
    ws_master = wb.create_sheet(title="Consolidated Daily Audits")
    ws_master.views.sheetView[0].showGridLines = True
    
    master_headers = [
        "Report Date", "Shift Window Covered", "S.No", "Light UID", "Region", "Zone / Sub-Division",
        "Run 1 (Prev 19:00)\n[Exp: ON]", "Run 2 (Prev 22:00)\n[Exp: OFF]",
        "Run 3 (Today 06:00)\n[Exp: ON]", "Run 4 (Today 07:00)\n[Exp: OFF]",
        "Overall Shift Status", "Compliance Remarks"
    ]
    for c_idx, h in enumerate(master_headers, 1):
        cell = ws_master.cell(row=1, column=c_idx, value=h)
        cell.font = font_header
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = grid_border
    ws_master.row_dimensions[1].height = 28
    
    for r_idx, rec in enumerate(master_records, 2):
        row_vals = [
            rec["report_date"], rec["shift_window"], rec["s_no"], rec["uid"], rec["region"], rec["zone"],
            rec["run1"], rec["run2"], rec["run3"], rec["run4"],
            rec["overall_status"], rec["remarks"]
        ]
        
        for c_idx, val in enumerate(row_vals, 1):
            cell = ws_master.cell(row=r_idx, column=c_idx, value=val)
            cell.font = font_regular
            cell.alignment = Alignment(horizontal="center" if c_idx not in [4, 12] else ("left" if c_idx == 12 else "center"), vertical="center")
            cell.border = grid_border
            
            # Format slot cells
            if c_idx == 7: # Run 1 (Prev 19:00 - exp ON)
                if val == "ON": cell.fill, cell.font = fill_on_good, font_on_good
                elif val == "OFF": cell.fill, cell.font = fill_off_bad, font_off_bad
                elif val == "UPCOMING": cell.fill, cell.font = fill_upcoming, font_upcoming
                else: cell.fill, cell.font = fill_unknown, font_unknown
            elif c_idx == 8: # Run 2 (Prev 22:00 - exp OFF)
                if val == "OFF": cell.fill, cell.font = fill_off_good, font_off_good
                elif val == "ON": cell.fill, cell.font = fill_on_bad, font_on_bad
                elif val == "UPCOMING": cell.fill, cell.font = fill_upcoming, font_upcoming
                else: cell.fill, cell.font = fill_unknown, font_unknown
            elif c_idx == 9: # Run 3 (Today 06:00 - exp ON)
                if val == "ON": cell.fill, cell.font = fill_on_good, font_on_good
                elif val == "OFF": cell.fill, cell.font = fill_off_bad, font_off_bad
                elif val == "UPCOMING": cell.fill, cell.font = fill_upcoming, font_upcoming
                else: cell.fill, cell.font = fill_unknown, font_unknown
            elif c_idx == 10: # Run 4 (Today 07:00 - exp OFF)
                if val == "OFF": cell.fill, cell.font = fill_off_good, font_off_good
                elif val == "ON": cell.fill, cell.font = fill_on_bad, font_on_bad
                elif val == "UPCOMING": cell.fill, cell.font = fill_upcoming, font_upcoming
                else: cell.fill, cell.font = fill_unknown, font_unknown
            elif c_idx == 11: # Overall Status
                if val == "Good & Efficiently Operative": cell.fill, cell.font = fill_badge_good, font_badge_good
                elif val == "Upcoming Shift": cell.fill, cell.font = fill_badge_pending, font_badge_pending
                else: cell.fill, cell.font = fill_badge_bad, font_badge_bad

    ws_master.freeze_panes = "A2"

    # ------------------ SHEET 3: DATE-WISE PIVOT MATRIX ------------------
    ws_matrix = wb.create_sheet(title="Date-Wise Shift Matrix")
    ws_matrix.views.sheetView[0].showGridLines = True
    
    ws_matrix.cell(row=1, column=1, value="Light Metadata").fill = header_fill
    ws_matrix.cell(row=1, column=1).font = font_header
    ws_matrix.merge_cells("A1:C1")
    
    ws_matrix.cell(row=2, column=1, value="S.No").fill = sub_header_fill
    ws_matrix.cell(row=2, column=1).font = font_sub_header
    ws_matrix.cell(row=2, column=1).alignment = Alignment(horizontal="center", vertical="center")
    
    ws_matrix.cell(row=2, column=2, value="Light UID").fill = sub_header_fill
    ws_matrix.cell(row=2, column=2).font = font_sub_header
    ws_matrix.cell(row=2, column=2).alignment = Alignment(horizontal="center", vertical="center")
    
    ws_matrix.cell(row=2, column=3, value="Zone / Sub-Division").fill = sub_header_fill
    ws_matrix.cell(row=2, column=3).font = font_sub_header
    ws_matrix.cell(row=2, column=3).alignment = Alignment(horizontal="center", vertical="center")
    
    col_tracker = 4
    date_col_map = {} # (report_date_str, run_num) -> col_index
    for r_date in report_dates:
        d_str = r_date.strftime("%Y-%m-%d")
        prev_d_str = (r_date - timedelta(days=1)).strftime("%b %d")
        curr_d_str = r_date.strftime("%b %d")
        
        # Merge header for the 4 shift runs
        c_date = ws_matrix.cell(row=1, column=col_tracker, value=f"Report: {curr_d_str} ({prev_d_str} Night -> {curr_d_str} Morning)")
        c_date.fill = header_fill if r_date.day % 2 == 0 else sub_header_fill
        c_date.font = font_header
        c_date.alignment = Alignment(horizontal="center", vertical="center")
        ws_matrix.merge_cells(start_row=1, start_column=col_tracker, end_row=1, end_column=col_tracker+3)
        
        for s_def in shift_definitions:
            r_num = s_def["run"]
            lbl = f"R{r_num} {s_def['slot']}\n({s_def['expected']})"
            c_slot = ws_matrix.cell(row=2, column=col_tracker, value=lbl)
            c_slot.fill = sub_header_fill if r_date.day % 2 == 0 else PatternFill(start_color="3B6EA5", end_color="3B6EA5", fill_type="solid")
            c_slot.font = Font(name="Calibri", size=9, bold=True, color="FFFFFF")
            c_slot.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            c_slot.border = grid_border
            date_col_map[(d_str, r_num)] = col_tracker
            col_tracker += 1
            
    ws_matrix.row_dimensions[1].height = 22
    ws_matrix.row_dimensions[2].height = 24
    
    for r_idx, uid in enumerate(light_uids, 3):
        info = device_data[uid]
        ws_matrix.cell(row=r_idx, column=1, value=r_idx-2).alignment = Alignment(horizontal="center")
        ws_matrix.cell(row=r_idx, column=2, value=uid).alignment = Alignment(horizontal="center")
        ws_matrix.cell(row=r_idx, column=3, value=info["zone"]).alignment = Alignment(horizontal="left")
        
        for c in range(1, 4):
            ws_matrix.cell(row=r_idx, column=c).border = grid_border
            ws_matrix.cell(row=r_idx, column=c).font = font_bold if c == 2 else font_regular
            
        for r_date in report_dates:
            d_str = r_date.strftime("%Y-%m-%d")
            for s_def in shift_definitions:
                r_num = s_def["run"]
                col_idx = date_col_map[(d_str, r_num)]
                target_day = r_date + timedelta(days=s_def["day_offset"])
                slot_dt = datetime(target_day.year, target_day.month, target_day.day, s_def["hour"], s_def["minute"])
                st, _, _ = evaluate_status(info["entries"], slot_dt)
                
                cell = ws_matrix.cell(row=r_idx, column=col_idx, value=st)
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.border = grid_border
                
                exp = s_def["expected"]
                if st == "UPCOMING":
                    cell.fill, cell.font = fill_upcoming, font_upcoming
                elif st == "ON":
                    if exp == "ON": cell.fill, cell.font = fill_on_good, font_on_good
                    else: cell.fill, cell.font = fill_on_bad, font_on_bad
                elif st == "OFF":
                    if exp == "OFF": cell.fill, cell.font = fill_off_good, font_off_good
                    else: cell.fill, cell.font = fill_off_bad, font_off_bad
                else:
                    cell.fill, cell.font = fill_unknown, font_unknown

    ws_matrix.freeze_panes = "D3"

    # ------------------ SHEET 4: DETAILED TELEMETRY LOG ------------------
    ws_raw = wb.create_sheet(title="Detailed Telemetry Log")
    ws_raw.views.sheetView[0].showGridLines = True
    
    raw_headers = [
        "Report Date", "Shift Window", "Run #", "Run Description", "Scheduled Time",
        "Light UID", "Region", "Zone / Sub-Division", "Expected Status", "Actual Status",
        "Raw Value", "Device Telemetry Timestamp", "Compliance Evaluation"
    ]
    for c_idx, h in enumerate(raw_headers, 1):
        cell = ws_raw.cell(row=1, column=c_idx, value=h)
        cell.font = font_header
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = grid_border
    ws_raw.row_dimensions[1].height = 26
    
    for r_idx, r_log in enumerate(raw_slot_logs, 2):
        row_vals = [
            r_log["report_date"], r_log["shift_window"], r_log["run_number"], r_log["run_desc"],
            r_log["scheduled_time"], r_log["uid"], r_log["region"], r_log["zone"],
            r_log["expected_status"], r_log["actual_status"], r_log["raw_value"],
            r_log["telemetry_timestamp"], r_log["compliance"]
        ]
        for c_idx, val in enumerate(row_vals, 1):
            cell = ws_raw.cell(row=r_idx, column=c_idx, value=val)
            cell.font = font_regular
            cell.alignment = Alignment(horizontal="center" if c_idx not in [6, 7, 11, 12] else "left", vertical="center")
            cell.border = grid_border
            if c_idx == 13:
                if val == "PASS": cell.fill, cell.font = fill_badge_good, font_badge_good
                elif val == "FAIL": cell.fill, cell.font = fill_badge_bad, font_badge_bad
                else: cell.fill, cell.font = fill_badge_pending, font_badge_pending

    ws_raw.freeze_panes = "A2"

    # Auto-fit Column Widths
    for ws in [ws_sum, ws_master, ws_matrix, ws_raw]:
        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                if cell.value:
                    lines = str(cell.value).split("\n")
                    for l in lines:
                        if len(str(l)) > max_len:
                            max_len = len(str(l))
            ws.column_dimensions[col_letter].width = max(max_len + 3, 11)

    ws_sum.column_dimensions["A"].width = 16
    ws_sum.column_dimensions["B"].width = 30
    ws_sum.column_dimensions["D"].width = 22
    ws_sum.column_dimensions["E"].width = 22
    ws_sum.column_dimensions["F"].width = 22
    ws_sum.column_dimensions["G"].width = 22
    ws_sum.column_dimensions["K"].width = 22
    
    ws_master.column_dimensions["A"].width = 14
    ws_master.column_dimensions["B"].width = 32
    ws_master.column_dimensions["D"].width = 18
    ws_master.column_dimensions["F"].width = 22
    ws_master.column_dimensions["K"].width = 28
    ws_master.column_dimensions["L"].width = 44
    
    ws_matrix.column_dimensions["A"].width = 8
    ws_matrix.column_dimensions["B"].width = 18
    ws_matrix.column_dimensions["C"].width = 22

    output_filename = f"BBMP_Park_Lights_Audit_Report_2026-08-21_to_{now.strftime('%Y-%m-%d')}.xlsx"
    output_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), output_filename)
    try:
        wb.save(output_path)
    except PermissionError:
        output_filename = f"BBMP_Park_Lights_Audit_Report_2026-08-21_to_{now.strftime('%Y-%m-%d')}_OvernightShifts.xlsx"
        output_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), output_filename)
        wb.save(output_path)
        
    print(f"\n=======================================================")
    print(f"SUCCESS: Accurate Overnight Shift Report generated!")
    print(f"File Path: {output_path}")
    print(f"File Size: {os.path.getsize(output_path) / 1024:.1f} KB")
    print(f"=======================================================")
    return output_path

if __name__ == "__main__":
    generate_report()
