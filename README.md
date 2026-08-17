# BBMP Park Light Relay Status Monitoring & Automated Email Dashboard

An automated Python solution that integrates with **ThingsBoard REST API** to check the relay status of park lights at designated daylight checkpoints (**7:30 AM** and **9:30 AM**). The system detects lights burning unnecessarily outside park operational hours to save energy and dispatches an automated HTML email dashboard.

---

## 🌟 Features

- **ThingsBoard REST API Client**: Authenticates via JWT (`/api/auth/login`) and retrieves real-time telemetry/timeseries data (`/api/plugins/telemetry/DEVICE/{deviceId}/values/timeseries`).
- **Scheduled Checkpoints (07:30 & 09:30)**: Uses `APScheduler` cron triggers to run daily status checks automatically.
- **7:30 AM vs 9:30 AM Comparison Matrix**: Maintains audit history and renders a side-by-side comparison matrix of relay status for all light UIDs.
- **Automated HTML Email Dashboard**: Formats alerts, total lights count, compliance rates, and color-coded status badges into a responsive HTML email sent via SMTP.
- **Offline HTML Preview**: Saves generated HTML email reports to `logs/` for offline inspection or testing.

---

## 📁 Project File Structure

```
d:\Schnell\BBMP_Park_Lights\
├── .env                       # Active configuration file (Credentials, UIDs, SMTP)
├── .env.example               # Configuration template
├── requirements.txt           # Python dependencies (requests, python-dotenv, apscheduler)
├── thingsboard_client.py      # ThingsBoard JWT Auth & Telemetry retriever
├── storage.py                 # Persistent JSON store for daily audit logs
├── email_reporter.py          # HTML Dashboard generator & SMTP dispatcher
├── test_audit.py              # Instant audit test runner (run audit right now)
├── main.py                    # Background scheduler daemon for 7:30 AM & 9:30 AM
└── README.md
```

---

## ⚙️ Configuration Setup

Edit your `.env` file with your specific ThingsBoard credentials, light UIDs, and email server parameters:

```env
# ThingsBoard Configuration
THINGSBOARD_HOST=https://schnelliot.in
THINGSBOARD_USERNAME=your_username@example.com
THINGSBOARD_PASSWORD=your_password

# List of Light UIDs (Device IDs or Device Names, comma-separated)
LIGHT_UIDS=PARK_LIGHT_01,PARK_LIGHT_02,PARK_LIGHT_03,PARK_LIGHT_04,PARK_LIGHT_05

# Telemetry key to check for relay status (e.g. relayStatus, status, state, relay)
TELEMETRY_RELAY_KEY=relayStatus

# Audit Schedule Configuration (24-hour HH:MM format)
AUDIT_TIMINGS=07:30,09:30

# Email Notification / SMTP Configuration
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USE_TLS=True
SMTP_USERNAME=your_email@gmail.com
SMTP_PASSWORD=your_app_password
SENDER_EMAIL=your_email@gmail.com
RECIPIENT_EMAILS=admin@bbmp.gov.in,supervisor@bbmp.gov.in
```

---

## 🚀 How to Run

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run Instant Test (Manual Trigger)
To fetch light statuses from ThingsBoard and generate the HTML email dashboard preview right now:

```bash
# Test 7:30 AM audit check
python test_audit.py 07:30

# Test 9:30 AM audit check
python test_audit.py 09:30
```
This will log the status of each UID and save an HTML preview in `logs/email_report_YYYYMMDD_HHMM.html`.

### 3. Start Automated Background Service
To run the automated scheduler that triggers every day at **7:30 AM** and **9:30 AM**:

```bash
python main.py
```

---

## 📧 Sample Email Dashboard Output

The email report includes:
- **Header**: Audit timestamp and time slot.
- **Alert Banner**: Highlights lights detected ON during daylight hours (`BBMP_PARK_LIGHT_02`, `BBMP_PARK_LIGHT_04`).
- **KPI Metrics**: Total lights, lights OFF (normal daylight state), lights BURNING (fault), and energy compliance rate %.
- **Matrix Table**: Detailed comparison table showing **7:30 AM Status**, **9:30 AM Status**, and **Current Status** per Light UID.
