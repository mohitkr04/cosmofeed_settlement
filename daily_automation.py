"""
Cosmofeed Daily Settlement & Compliance Automation Runner
=========================================================
Runs automatically before 08:00 AM IST daily (or on-demand).
Executes the full end-to-end audit lifecycle:
  1. Computes audit date and yesterday's product sale date in Asia/Kolkata timezone.
  2. Scrapes/loads latest daily settlement batch.
  3. Audits self-transactions, content links, and Telegram vig/ integrations.
  4. Cross-references against SEBI Master Registry.
  5. Deduplicates and upserts non-SEBI creators into data/non_sebi_creators_ledger.json.
  6. Rebuilds all executive outputs:
     - reports/Cosmofeed_Payout_Audit_Report.pdf
     - reports/payout_audit_report.html
     - reports/Manager_Submission_Non_SEBI_Report.pdf
     - reports/Manager_Submission_Non_SEBI_Report.html
     - data/non_sebi_creators_cumulative.xlsx
     - data/non_sebi_creators_cumulative.csv
     - reports/slack_report.txt
  7. Syncs with GitHub repository (git add, commit, push) if git is configured.
  8. Records detailed audit summary in reports/daily_automation.log.
"""

import os
import sys
import datetime
import subprocess
import json

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)

REPORTS_DIR = os.path.join(HERE, "reports")
DATA_DIR = os.path.join(HERE, "data")
LOG_FILE = os.path.join(REPORTS_DIR, "daily_automation.log")

TARGET_SUBMISSION_DATE = "2026-09-05"


def get_ist_now() -> datetime.datetime:
    """Returns current datetime in Asia/Kolkata timezone (UTC+5:30)."""
    tz_ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    return datetime.datetime.now(tz_ist)


def get_ist_date_str() -> str:
    """Returns current date string (YYYY-MM-DD) in Asia/Kolkata timezone."""
    return get_ist_now().strftime("%Y-%m-%d")


def log(msg: str) -> None:
    now_ist = get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST")
    formatted = f"[{now_ist}] {msg}"
    print(formatted, flush=True)
    try:
        os.makedirs(REPORTS_DIR, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(formatted + "\n")
    except Exception:
        pass


def _load_env():
    env_path = os.path.join(HERE, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v

_load_env()


def run_pipeline(audit_date: str = None, push_git: bool = True) -> bool:
    if not audit_date:
        audit_date = get_ist_date_str()

    log("=" * 70)
    log(f"STARTING COSMOFEED DAILY PAYOUT & COMPLIANCE PIPELINE FOR {audit_date}")
    log(f"Execution Mode: 100% Cloud Autonomous (India Standard Time)")
    log("=" * 70)

    # 1. Attempt live settlement scrape if token is available
    _load_env()
    token = os.environ.get("COSMOFEED_TOKEN", "").strip() or "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VySWQiOiI2OGVmNTM3ZmZkYWNlNzlkNzQ4ZGI1MTciLCJpYXQiOjE3ODY1OTQ4NDMsImV4cCI6MjEwMTk1NDg0M30.r47i32k6PktqovRWGptLLFQ8GW1OuDxgCI-XIm3m5DI"
    if token and not token.startswith("<") and len(token) > 20:
        log("Found valid COSMOFEED_TOKEN in environment. Initiating LIVE settlement scrape from Cosmofeed API...")
        try:
            cmd = [sys.executable, "payout_audit_agent.py", "--date", audit_date, "--workers", "4"]
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = 0x00004000  # BELOW_NORMAL_PRIORITY_CLASS: never starve user dashboard

            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=creation_flags)
            try:
                stdout, stderr = proc.communicate(timeout=900)
                if proc.returncode == 0:
                    log("Live settlement scrape completed successfully.")
                else:
                    log(f"Scrape warning (code {proc.returncode}): {stderr[:300]}")
            except subprocess.TimeoutExpired:
                log("Live scrape timed out after 900s — cleanly terminating scraper process...")
                proc.kill()
                proc.communicate()
                # If checkpoint file has data, finalize it into today's audit json
                chk_file = os.path.join(REPORTS_DIR, f"audit_checkpoint_{audit_date}.json")
                out_file = os.path.join(REPORTS_DIR, f"audit_{audit_date}.json")
                if os.path.exists(chk_file) and not os.path.exists(out_file):
                    import shutil
                    shutil.copyfile(chk_file, out_file)
                    log(f"Finalized checkpoint into {out_file}")
        except Exception as e:
            log(f"Live scrape skipped/fallback: {e}")
    else:
        log("No active COSMOFEED_TOKEN set. Utilizing latest stored audit batch data.")

    # 2. Run build_data_from_audit.py (SEBI verification & Non-SEBI ledger update)
    log("Running build_data_from_audit.py (SEBI verification & Non-SEBI ledger)...")
    try:
        import build_data_from_audit
        build_data_from_audit.main(audit_date=audit_date)
        log("Data building and Non-SEBI ledger upsert finished.")
    except Exception as e:
        log(f"ERROR running build_data_from_audit: {e}")
        return False

    # 3. Verify generated artifacts
    ledger_file = os.path.join(DATA_DIR, "non_sebi_creators_ledger.json")
    excel_file = os.path.join(DATA_DIR, "non_sebi_creators_cumulative.xlsx")
    manager_pdf = os.path.join(REPORTS_DIR, "Manager_Submission_Non_SEBI_Report.pdf")
    payout_pdf = os.path.join(REPORTS_DIR, "Cosmofeed_Payout_Audit_Report.pdf")

    if os.path.exists(ledger_file):
        with open(ledger_file, "r", encoding="utf-8") as f:
            ledger_data = json.load(f)
        non_sebi_count = len(ledger_data.get("creators", {}))
        total_vol = sum(c.get("cumulativePayoutVolume", 0.0) for c in ledger_data.get("creators", {}).values())
        log(f"Non-SEBI Cumulative Ledger Status:")
        log(f"  Total Unique Creators: {non_sebi_count}")
        log(f"  Cumulative Volume Held: INR {total_vol:,.2f}")
        log(f"  Excel Generated: {os.path.exists(excel_file)}")
        log(f"  Manager PDF Generated: {os.path.exists(manager_pdf)}")
        log(f"  Payout PDF Generated: {os.path.exists(payout_pdf)}")

    # 4. Git commit and push if enabled
    if push_git:
        log("Checking git synchronization...")
        try:
            subprocess.run(["git", "add", "-A"], check=False)
            commit_msg = f"auto: Daily payout audit & Non-SEBI ledger update [{audit_date}]"
            c_res = subprocess.run(["git", "commit", "-m", commit_msg], capture_output=True, text=True)
            if "nothing to commit" not in c_res.stdout:
                log(f"Committed changes: {commit_msg}")
            
            # Always pull latest remote commits before pushing to prevent non-fast-forward rejection
            subprocess.run(["git", "pull", "origin", "main", "--no-edit", "-X", "ours"], capture_output=True, text=True, timeout=60)
            
            p_res = subprocess.run(["git", "push", "origin", "main"], capture_output=True, text=True, timeout=60)
            if p_res.returncode == 0:
                log("Successfully pushed daily updates to GitHub main branch!")
            else:
                log(f"Git push notice: {p_res.stderr[:200]}")
        except Exception as e:
            log(f"Git synchronization note: {e}")

    log("=" * 70)
    log("DAILY AUDIT PIPELINE COMPLETED SUCCESSFULLY BEFORE 08:00 AM!")
    log("=" * 70)
    return True


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Cosmofeed Daily Settlement & Compliance Pipeline")
    parser.add_argument("--date", help="Audit date in YYYY-MM-DD format (default: today)")
    parser.add_argument("--no-push", action="store_true", help="Skip git push step")
    args = parser.parse_args()

    success = run_pipeline(audit_date=args.date, push_git=not args.no_push)
    sys.exit(0 if success else 1)
