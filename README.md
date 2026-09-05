# Room Check-In Bot

Automatically checks you into ERAU Hazy Library room reservations using a
Google Sheet as your entry list.

## How it works

1. You add a row to a Google Sheet with the reservation's **Date**, **Time**,
   and **Code** (from the confirmation email).
2. A script runs every 5 minutes (for free, via GitHub Actions) and checks
   whether any reservation's 30-minute check-in window (15 min before to
   15 min after the start time) is currently open.
3. If so, it opens the check-in page, fills in your email and the code, and
   submits — then marks that row "Done" so it won't try again.

## One-time setup

### 1. Create the Google Sheet

Make a new Google Sheet with this exact header row:

| Date       | Time  | Code   | Status |
|------------|-------|--------|--------|
| 2026-09-10 | 14:30 | ABC123 |        |

- **Date** format: `YYYY-MM-DD`
- **Time** format: 24-hour `HH:MM` (e.g. `14:30` for 2:30 PM)
- **Status**: leave blank — the bot fills in `Done` or `Failed`

Copy the Sheet ID out of its URL:
`https://docs.google.com/spreadsheets/d/`**`THIS_PART`**`/edit`

### 2. Create a Google service account (so the script can read/write the sheet)

1. Go to https://console.cloud.google.com/ and create a new project (or use an existing one).
2. Enable the **Google Sheets API** for that project (APIs & Services → Library → search "Google Sheets API" → Enable).
3. Go to APIs & Services → Credentials → Create Credentials → **Service Account**. Give it any name.
4. Open the new service account → Keys → Add Key → **Create new key** → JSON. This downloads a `.json` file — keep it private.
5. Open that JSON file and copy the `client_email` value (looks like `something@your-project.iam.gserviceaccount.com`).
6. In your Google Sheet, click **Share** and share it with that email address as an **Editor**.

### 3. Put this project on GitHub

1. Create a new (private is fine) GitHub repo and push these files to it:
   `checkin.py`, `requirements.txt`, `.github/workflows/checkin.yml`.

### 4. Add your secrets

In the repo: Settings → Secrets and variables → Actions → New repository secret. Add two:

- `SHEET_ID` — the Sheet ID from step 1
- `GOOGLE_CREDENTIALS_JSON` — paste the **entire contents** of the service account JSON file from step 2

### 5. Test it manually

Go to the repo's **Actions** tab → "Room Check-In Bot" → **Run workflow** to trigger it by hand.
Check the run's logs to see what it found and did.

Add a test row to your sheet with a Date/Time set to a few minutes from now
(using a throwaway/expired code) and run the workflow manually to confirm it
finds the row, attempts a check-in, and updates the Status column.

## Important: verify the success/failure detection

I wrote `checkin.py` based on the check-in page's visible labels ("Email",
"Check In Code", "Check In" button), which should be stable. However, I
could not see what the page displays after a **successful** vs **failed**
submission, since that only appears after actually submitting a code. Look
at the bottom of `checkin.py` for this section:

```python
success_markers = ["checked in", "success", "thank you"]
failure_markers = ["invalid", "error", "not found", "expired"]
```

After your first real check-in (or a deliberate test with a wrong code),
open the workflow logs or add a debug screenshot, see what message the page
actually shows, and update these lists to match. Until then, it defaults to
treating ambiguous results as "not done yet" so it retries rather than
silently failing.

## Notes

- GitHub Actions' free tier easily covers running this every 5 minutes.
- The schedule can lag by a few minutes under GitHub's load; the 30-minute
  window gives you buffer, but check in early when you can.
- Time zone is set to `America/Phoenix` (Arizona, no DST) in `checkin.py` —
  change `TIMEZONE` if that's ever not correct for you.
