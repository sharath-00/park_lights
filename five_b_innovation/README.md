# 5B Innovation Park Lights Monitoring & Energy Audit Dashboard

An automated Python solution that integrates **Google Sheets (via Google Service Account `service.json`)** and the **ThingsBoard REST API** to audit the relay state of park lights across 5B Innovation project sites.

The system ensures lights are active during scheduled park operating hours and flags unnecessary daytime or unscheduled burning to reduce energy consumption, dispatching daily executive HTML email dashboards and generating stylized Excel reports.

---

## 🌟 Key Features

1. **Google Sheets Integration (`service.json`)**:
   - Authenticates using Google Service Account credentials (`gspread` / `google-auth`).
   - Dynamically parses park lights inventory (UIDs, panel names, regions, zones, evening slots, morning slots).
   - Multi-tier resilience: API -> Published Google Sheets URL -> Offline cache (`data/5b_park_panels.csv`).

2. **ThingsBoard IoT Platform Integration**:
   - Uses customer UUID `3e268290-3989-11f1-9e5f-85a6074555d7` (5B Innovation).
   - Fetches telemetry for relay key `rly`.
   - Audits 4 shift checkpoints:
     - **Run 1: 19:00 (Evening 7:00 PM)** (Expected: ON) - Evening Shift Start
     - **Run 2: 22:00 (Evening 10:00 PM)** (Expected: OFF) - Evening Shutoff / Night Off
     - **Run 3: 05:00 (Morning 5:00 AM)** (Expected: ON) - Morning Shift Start
     - **Run 4: 07:00 (Morning 7:00 AM)** (Expected: OFF) - Daylight Shutoff (prevents daytime waste)

3. **Multi-Channel Dashboards**:
   - **Executive HTML Email Report**: Includes KPI cards, zone-wise breakdown, and a complete 4-checkpoint comparison matrix.
   - **Multi-Tab Styled Excel Workbook**: Generates formatted `.xlsx` files with KPI summary, zone analysis, and cell color-coding.
   - **Offline HTML Preview**: Saves generated dashboard previews to `logs/` for offline inspection.

---

## 📁 Folder Structure

```
d:\Schnell\BBMP_Park_Lights\five_b_innovation\
├── .env                         # Active credentials & configuration
├── .env.example                 # Configuration template
├── service.json                 # Google Service Account credentials
├── requirements.txt             # Python package dependencies
├── config.py                    # Environment configuration loader
├── google_sheets_client.py      # Google Sheets reader & UID extractor
├── thingsboard_client.py        # ThingsBoard REST API & 4-slot audit engine
├── storage.py                   # Persistent JSON audit history
├── email_reporter.py            # Responsive HTML email builder & SMTP sender
├── generate_excel_report.py     # Excel workbook generator (.xlsx)
├── main.py                      # Main pipeline CLI runner
├── data/
│   ├── 5b_park_panels.csv       # Cached panels inventory
│   └── audit_history.json       # Historical daily audit log
└── logs/                        # Generated HTML dashboards & Excel reports
```

---

## 🚀 Usage

### 1. Inspect & Verify Google Sheets Data
Check that Google Sheets credentials (`service.json`) and sheet parsing are working:
```bash
python main.py --sheet-info
```

### 2. Run Dry-Run Audit (Preview Only)
Fetches data, evaluates telemetry, creates HTML preview and Excel workbook without sending email:
```bash
python main.py --dry-run
```

### 3. Run Live Audit & Dispatch Email
Audits today's slots, creates reports, and dispatches the HTML dashboard via SMTP:
```bash
python main.py
```

### 4. Audit a Specific Date
```bash
python main.py 2026-10-31
```

