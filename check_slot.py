import os
from dotenv import load_dotenv
from thingsboard_client import ThingsBoardClient

def check_slot():
    load_dotenv()
    tb_host = os.getenv("THINGSBOARD_HOST")
    tb_user = os.getenv("THINGSBOARD_USERNAME")
    tb_pass = os.getenv("THINGSBOARD_PASSWORD")
    relay_key = os.getenv("TELEMETRY_RELAY_KEY", "rly")
    light_uids_raw = os.getenv("LIGHT_UIDS", "")
    light_uids = [u.strip() for u in light_uids_raw.split(",") if u.strip()]

    tb_client = ThingsBoardClient(host=tb_host, username=tb_user, password=tb_pass, relay_key=relay_key)
    daily_summary = tb_client.fetch_daily_4_slots_telemetry(light_uids, target_slots=["05:15"])
    
    audits = daily_summary.get("audits", {})
    slot_data = audits.get("05:15", {})
    
    print(f"--- Relay Status for 05:15 AM ---")
    print(f"Total Lights: {slot_data.get('total_lights')}")
    print(f"Burning (ON): {slot_data.get('burning_count')}")
    print(f"Off (OFF): {slot_data.get('off_count')}")
    print("---------------------------------")
    
    on_lights = [l['uid'] for l in slot_data.get('lights', []) if l.get('relay_status') == 'ON']
    if on_lights:
        print("Lights that are ON:")
        for uid in on_lights:
            print(f" - {uid}")

if __name__ == "__main__":
    check_slot()
