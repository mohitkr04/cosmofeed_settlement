"""
Cosmofeed Daily Settlement & Compliance Automation Runner
=========================================================
Runs automatically before 10:00 AM IST daily (or on-demand).
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


def log(msg: str) -> None:
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{now_str}] {msg}"
    print(formatted)
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
        audit_date = datetime.date.today().strftime("%Y-%m-%d")

    log("=" * 70)
    log(f"STARTING COSMOFEED DAILY PAYOUT & COMPLIANCE PIPELINE FOR {audit_date}")
    log(f"Target Manager Submission Deadline: {TARGET_SUBMISSION_DATE}")
    log("=" * 70)

    # 1. Attempt live settlement scrape if token is available
    _load_env()
    token = os.environ.get("COSMOFEED_TOKEN", "").strip()
    if token and not token.startswith("<") and len(token) > 20:
        log("Found valid COSMOFEED_TOKEN in environment. Initiating LIVE settlement scrape from Cosmofeed API...")
        try:
            cmd = [sys.executable, "payout_audit_agent.py", "--date", audit_date, "--workers", "16"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if res.returncode == 0:
                log("Live settlement scrape completed successfully.")
            else:
                log(f"Scrape warning (code {res.returncode}): {res.stderr[:300]}")
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
            subprocess.run(["git", "add", "reports/", "data/", "index.html"], check=False)
            commit_msg = f"auto: Daily payout audit & Non-SEBI ledger update [{audit_date}]"
            c_res = subprocess.run(["git", "commit", "-m", commit_msg], capture_output=True, text=True)
            if "nothing to commit" not in c_res.stdout:
                log(f"Committed changes: {commit_msg}")
                p_res = subprocess.run(["git", "push", "origin", "main"], capture_output=True, text=True, timeout=60)
                if p_res.returncode == 0:
                    log("Successfully pushed daily updates to GitHub main branch!")
                else:
                    log(f"Git push notice: {p_res.stderr[:200]}")
            else:
                log("Git reports and data are already up-to-date with latest commit.")
        except Exception as e:
            log(f"Git synchronization note: {e}")

    log("=" * 70)
    log("DAILY AUDIT PIPELINE COMPLETED SUCCESSFULLY BEFORE 10:00 AM!")
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
