"""
Auto check-in bot for ERAU Hazy Library room reservations.

Reads reservations (Date, Time, Code, Status) from a Google Sheet.
For any reservation whose check-in window is currently open
(15 minutes before to 15 minutes after the booked start time),
it opens the LibCal check-in page and submits the email + code.

Run this on a schedule (e.g. every 5 minutes via GitHub Actions).
"""

import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

# ---- Configuration (set these as environment variables / GitHub secrets) ----
SHEET_ID = os.environ["SHEET_ID"]
CHECKIN_EMAIL = os.environ["CHECKIN_EMAIL"]
GOOGLE_CREDENTIALS_JSON = os.environ["GOOGLE_CREDENTIALS_JSON"]  # full JSON key, as a string

CHECKIN_URL = "https://pr.erau.libcal.com/r/checkin"
TIMEZONE = "America/Phoenix"  # Arizona does not observe DST
WINDOW_MINUTES = 15  # minutes before/after start time the window is open

STATUS_PENDING = ""
STATUS_DONE = "Done"
STATUS_FAILED = "Failed"


def get_sheet():
    creds_path = "/tmp/gcreds.json"
    with open(creds_path, "w") as f:
        f.write(GOOGLE_CREDENTIALS_JSON)

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID).sheet1


def parse_reservation_time(date_str, time_str):
    """Expects Date like 2026-09-10 and Time like 14:30 (24hr) — adjust format as needed."""
    dt_str = f"{date_str} {time_str}"
    naive = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
    return naive.replace(tzinfo=ZoneInfo(TIMEZONE))


def do_checkin(code: str) -> bool:
    """Returns True if check-in appears successful."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(CHECKIN_URL, wait_until="networkidle")

        # Using label-based selectors so this survives minor HTML/ID changes.
        page.get_by_label("Email").fill(CHECKIN_EMAIL)
        page.get_by_label("Check In Code").fill(code)
        page.get_by_role("button", name="Check In").click()

        page.wait_for_timeout(3000)  # let the confirmation render

        content = page.content().lower()
        browser.close()

        # NOTE: You'll likely need to tune this after your first real test run,
        # based on what the actual success/error message says.
        success_markers = ["checked in", "success", "thank you"]
        failure_markers = ["invalid", "error", "not found", "expired"]

        if any(m in content for m in success_markers):
            return True
        if any(m in content for m in failure_markers):
            return False
        # Ambiguous — treat as failure so it retries next run rather than
        # silently being marked Done.
        return False


def main():
    sheet = get_sheet()
    rows = sheet.get_all_records()  # list of dicts, keyed by header row
    now = datetime.now(ZoneInfo(TIMEZONE))

    for idx, row in enumerate(rows, start=2):  # row 1 is the header
        status = str(row.get("Status", "")).strip()
        if status == STATUS_DONE:
            continue

        date_str = str(row.get("Date", "")).strip()
        time_str = str(row.get("Time", "")).strip()
        code = str(row.get("Code", "")).strip()

        if not date_str or not time_str or not code:
            continue

        try:
            start_time = parse_reservation_time(date_str, time_str)
        except ValueError:
            print(f"Row {idx}: couldn't parse date/time '{date_str} {time_str}', skipping.")
            continue

        window_start = start_time - timedelta(minutes=WINDOW_MINUTES)
        window_end = start_time + timedelta(minutes=WINDOW_MINUTES)

        if window_start <= now <= window_end:
            print(f"Row {idx}: within check-in window, attempting check-in with code {code}...")
            success = do_checkin(code)
            new_status = STATUS_DONE if success else STATUS_FAILED
            sheet.update_cell(idx, 4, new_status)  # column D = Status
            print(f"Row {idx}: {'succeeded' if success else 'failed'}.")
        else:
            print(f"Row {idx}: not in window yet (window {window_start} - {window_end}).")


if __name__ == "__main__":
    main()
