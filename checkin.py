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
    os.makedirs("/tmp/debug", exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        content = ""

        try:
            page.goto(CHECKIN_URL, wait_until="networkidle")

            # The real form only has a single "Check In Code" field
            # (id="s-lc-code", name="code") and a "Check In" button.
            # There's a separate hidden no-JS fallback form elsewhere in
            # the DOM that includes an email field, but the real, visible
            # form doesn't ask for one at all.
            page.wait_for_selector("#s-lc-code", state="visible", timeout=15000)
            page.locator("#s-lc-code").fill(code)
            page.get_by_role("button", name="Check In").click()

            page.wait_for_timeout(3000)  # let the confirmation render
        except Exception as e:
            print(f"Exception during check-in: {e}")
        finally:
            # Always capture what the page looked like, success or failure.
            page.screenshot(path="/tmp/debug/checkin_result.png", full_page=True)
            with open("/tmp/debug/checkin_result.html", "w") as f:
                f.write(page.content())
            content = page.content().lower()
            browser.close()

        # NOTE: If this still misjudges success/failure, check the debug
        # screenshot/HTML after a real attempt and adjust below. Two ways
        # to tell them apart, in order of reliability:
        #   1. The #s-lc-code input disappearing from the page (usually
        #      means it was accepted and replaced with a confirmation).
        #   2. Wording on the resulting page (fallback, less reliable).
        code_field_gone = "s-lc-code" not in content

        success_markers = ["checked in", "success", "thank you"]
        failure_markers = ["invalid", "error", "not found", "expired"]

        if code_field_gone or any(m in content for m in success_markers):
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
    print(f"Current time ({TIMEZONE}): {now}")
    print(f"Read {len(rows)} row(s) from sheet. Headers found: {list(rows[0].keys()) if rows else 'N/A'}")

    for idx, row in enumerate(rows, start=2):  # row 1 is the header
        print(f"--- Row {idx} raw data: {row}")

        status = str(row.get("Status", "")).strip()
        if status == STATUS_DONE:
            print(f"Row {idx}: already marked Done, skipping.")
            continue

        date_str = str(row.get("Date", "")).strip()
        time_str = str(row.get("Time", "")).strip()
        code = str(row.get("Code", "")).strip()

        if not date_str or not time_str or not code:
            print(f"Row {idx}: missing Date/Time/Code (got Date='{date_str}', Time='{time_str}', Code='{code}'), skipping.")
            continue

        try:
            start_time = parse_reservation_time(date_str, time_str)
        except ValueError:
            print(f"Row {idx}: couldn't parse date/time '{date_str} {time_str}' (expected 'YYYY-MM-DD' and 'HH:MM'), skipping.")
            continue

        window_start = start_time - timedelta(minutes=WINDOW_MINUTES)
        window_end = start_time + timedelta(minutes=WINDOW_MINUTES)
        print(f"Row {idx}: window is {window_start} to {window_end}")

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
