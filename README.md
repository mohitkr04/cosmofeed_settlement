# 🛡️ Cosmofeed Executive Intelligence — Daily Payout Audit & SEBI Compliance

An enterprise-grade compliance auditing tool, deduplicated creator management ledger, and executive dashboard designed to inspect **Cosmofeed pending settlements (payouts)**, detect unauthorized **Telegram integration (`vig/{productId}`)**, enforce **SEBI Master Registry compliance**, isolate **self-transactions within strict 2-day rolling windows**, and automate daily audit workflows **before 10:00 AM IST each day**.

---

## 📌 Table of Contents
1. [🎯 Executive Overview & Objectives](#-1-executive-overview--objectives)
2. [📊 Non-SEBI Creator Cumulative Ledger (Until 5 September)](#-2-non-sebi-creator-cumulative-ledger-until-5-september)
3. [⏰ Daily Automated Workflow (Runs Before 10:00 AM IST)](#-3-daily-automated-workflow-runs-before-1000-am-ist)
4. [🌐 Hosted Dashboard & Live URLs](#-4-hosted-dashboard--live-urls)
5. [📑 Manager Submission Reports (PDF, HTML, Excel, CSV)](#-5-manager-submission-reports-pdf-html-excel-csv)
6. [🔍 Audit Modules & Risk Logic](#-6-audit-modules--risk-logic)
7. [📁 Repository Structure](#-7-repository-structure)
8. [🚀 Setup & Quick Start Guide](#-8-setup--quick-start-guide)
9. [🐙 GitHub Actions & CI/CD Deployment](#-9-github-actions--cicd-deployment)

---

## 🎯 1. Executive Overview & Objectives

### The Problem
During daily settlement cycles, fintech and creator monetization networks face regulatory, financial, and compliance risks:
- **Unregistered Investment Advisory via Telegram**: Creators offering financial, trading, or stock advisory via Telegram channels (`vig/{productId}`) without valid Securities and Exchange Board of India (**SEBI**) registration numbers.
- **Self-Transactions**: Creators purchasing their own digital products to inflate revenue, cash out illicit funds, or bypass fee schedules.
- **Missing Product Deliverables**: Products with no attached files, videos, or course modules.
- **Repeat Non-SEBI Offenders**: Unregistered creators submitting recurring settlement batches across multiple days.

### The Solution
This automated suite provides:
1. **Automated Telegram & SEBI Verification**: Automatically isolates all settlements $\ge$ ₹1,000 using Telegram (`vig/{productId}`), extracts creator metadata, and matches them against the organization's verified **SEBI Master Registry** (`sebi_master_creators.xlsx`).
2. **Strict Non-SEBI Deduplication Ledger**: Tracks all non-SEBI creators across daily settlement runs through **5 September 2026** into a persistent ledger (`data/non_sebi_creators_ledger.json`) without any repeated entries.
3. **Daily Automation Before 10:00 AM IST**: Runs every morning at **09:00 AM IST** via GitHub Actions and local Windows Task Scheduler, regenerating reports and updating the live dashboard.
4. **Self-Transaction 2-Day Allowed Window**: Strictly sorts self-payments:
   $$\mathbf{27\text{ Aug (Today)}} \longrightarrow \mathbf{26\text{ Aug (Yesterday)}} \longrightarrow \mathbf{25\text{ Aug (Window Buffer)}}$$
   Sorted strictly from **Highest Self-Transaction Amount to Lowest** within each day.

---

## 📊 2. Non-SEBI Creator Cumulative Ledger (Until 5 September)

To comply with organizational reporting requirements, all creators utilizing Telegram integrations without verified SEBI registration are systematically recorded in a persistent store until **5 September 2026**.

### Deduplication Policy & Data Guarantees
- **Primary Key**: MongoDB 24-character hexadecimal `creatorId` (normalized).
- **Single Master Row**: If a creator appears in today's settlement batch and again tomorrow, **no duplicate entry is created**.
- **Running Aggregates**:
  - `firstSeenDate`: The initial audit date the creator was detected.
  - `lastSeenDate`: The most recent settlement batch date.
  - `daysFlaggedCount`: Total number of distinct daily settlement runs where the creator appeared.
  - `datesObserved`: Array of all audit dates where settlements were attempted.
  - `latestPayoutAmount`: Most recent pending settlement amount.
  - `cumulativePayoutVolume`: Running sum of all settlement amounts held across all observed dates.
  - `maxDailyPayout`: Maximum settlement amount observed in a single batch.
  - `telegramProductIds` & `telegramProductLinks`: Set of all Telegram products used.
  - `complianceHoldStatus`: Defaulted to `HOLD - RELEASE RESTRICTED`.

### Designated Storage Locations
| Artifact | File Path | Format | Description |
| :--- | :--- | :--- | :--- |
| **JSON Ledger** | [`data/non_sebi_creators_ledger.json`](file:///c:/Users/Mindf/cosmofeed_settlement/data/non_sebi_creators_ledger.json) | JSON | Canonical source of truth for programmatic ingestion and daily upserts. |
| **Master Excel** | [`data/non_sebi_creators_cumulative.xlsx`](file:///c:/Users/Mindf/cosmofeed_settlement/data/non_sebi_creators_cumulative.xlsx) | XLSX | Executive multi-sheet workbook with KPI summary cards, master deduplicated registry, and daily audit breakdown. |
| **Master CSV** | [`data/non_sebi_creators_cumulative.csv`](file:///c:/Users/Mindf/cosmofeed_settlement/data/non_sebi_creators_cumulative.csv) | CSV | Clean flat dataset for external data warehousing and analytics. |
| **Manager Submission HTML** | [`reports/Manager_Submission_Non_SEBI_Report.html`](file:///c:/Users/Mindf/cosmofeed_settlement/reports/Manager_Submission_Non_SEBI_Report.html) | HTML | Self-contained executive report with manager sign-off blocks. |
| **Manager Submission PDF** | [`reports/Manager_Submission_Non_SEBI_Report.pdf`](file:///c:/Users/Mindf/cosmofeed_settlement/reports/Manager_Submission_Non_SEBI_Report.pdf) | PDF | Formal landscape PDF report with compliance acknowledgement signature lines. |

---

## ⏰ 3. Daily Automated Workflow (Runs Before 10:00 AM IST)

The entire settlement audit and report updating process is fully automated to complete **before 10:00 AM IST each morning**:

```
09:00 AM IST (03:30 UTC)
   │
   ├─► 1. Fetch Today's Settlements (payout_audit_agent.py)
   │      - Queries IDgetSettlements & IDgetSettlementDetails in Asia/Kolkata timezone
   │
   ├─► 2. Audit Findings & SEBI Verifier (build_data_from_audit.py & telegram_sebi_verifier.py)
   │      - Filters payout >= ₹1,000
   │      - Detects vig/ Telegram products
   │      - Matches against sebi_master_creators.xlsx
   │
   ├─► 3. Non-SEBI Ledger Upsert (non_sebi_manager.py)
   │      - Deduplicates by creatorId into non_sebi_creators_ledger.json
   │      - Rebuilds non_sebi_creators_cumulative.xlsx & .csv
   │
   ├─► 4. Executive Report Generation (generate_report.py & generate_pdf.py)
   │      - Rebuilds Cosmofeed_Payout_Audit_Report.pdf & payout_audit_report.html
   │      - Generates Manager_Submission_Non_SEBI_Report.pdf & .html
   │      - Generates slack_report.txt
   │
   └─► 5. Auto Git Sync & Deployment
          - Commits updated data/ and reports/ to GitHub main branch
          - Live server & Cloudflare tunnel immediately reflect updated data
          - GitHub Pages automatically deploys updated static dashboard
```

### Automation Triggers
1. **GitHub Actions Workflow** ([`.github/workflows/daily_audit.yml`](file:///c:/Users/Mindf/cosmofeed_settlement/.github/workflows/daily_audit.yml)):
   - Scheduled cron: `'30 3 * * *'` (03:30 AM UTC = **09:00 AM IST**).
   - Installs required dependencies (`requests`, `pandas`, `openpyxl`, `reportlab`).
   - Runs audit, updates reports and ledger, commits changes, and deploys to GitHub Pages.
2. **Local Windows Automation** ([`daily_automation.py`](file:///c:/Users/Mindf/cosmofeed_settlement/daily_automation.py)):
   - Run manually anytime: `python daily_automation.py`
   - Or double-click: [`run_daily_audit.bat`](file:///c:/Users/Mindf/cosmofeed_settlement/run_daily_audit.bat)
3. **Windows Task Scheduler Registration** ([`setup_daily_task.ps1`](file:///c:/Users/Mindf/cosmofeed_settlement/setup_daily_task.ps1)):
   - Run in PowerShell to schedule `CosmofeedDailyPayoutAudit` at **09:00 AM IST** daily:
     ```powershell
     powershell -ExecutionPolicy Bypass -File .\setup_daily_task.ps1
     ```

---

## 🌐 4. Hosted Dashboard & Live URLs

The interactive compliance dashboard can be accessed in multiple hosting environments:

| Mode / Host | Access URL | Features | Status |
| :--- | :--- | :--- | :---: |
| 🚀 **Live Public HTTPS Tunnel** | **[https://limitations-quoted-index-nyc.trycloudflare.com](https://limitations-quoted-index-nyc.trycloudflare.com)** | Secured public Cloudflare tunnel. Accessible on any browser or mobile device worldwide. Full backend downloads active. | 🟢 **ACTIVE & LIVE** |
| 🌐 **24/7 Cloud Hosted (GitHub Pages)** | **[https://mohitkr04.github.io/cosmofeed_settlement/](https://mohitkr04.github.io/cosmofeed_settlement/)** | Permanent 24/7 global CDN hosted dashboard. Always up even when local laptop is offline. | 🟢 **ACTIVE & LIVE** |
| 💻 **Local Server** | **[http://localhost:8000/](http://localhost:8000/)** | Fast local HTTP server on `server.py`. | 🟢 **ACTIVE & LIVE** |
| 🐙 **GitHub Repository** | **[https://github.com/mohitkr04/cosmofeed_settlement](https://github.com/mohitkr04/cosmofeed_settlement)** | Code repository with automated CI/CD workflows and version history. | 🟢 **PUSHED & SYNCED** |

---

## 📑 5. Manager Submission Reports (PDF, HTML, Excel, CSV)

The dashboard and server provide direct one-click download endpoints for management submission:

| Endpoint | Content | Format |
| :--- | :--- | :---: |
| `/api/non-sebi/download-excel` | Cumulative Non-SEBI Master Excel (Executive Summary, Master Registry, Daily Breakdown) | `.xlsx` |
| `/api/non-sebi/download-pdf` | Executive Manager Submission Report with Compliance Sign-off Block | `.pdf` |
| `/api/non-sebi/download-csv` | Flat CSV dataset of all non-SEBI creators with volume metrics & contacts | `.csv` |
| `/api/non-sebi/manager-report` | Standalone Executive HTML Report | `.html` |
| `/api/download-pdf` | Daily Payout Audit Executive Multi-Page PDF Report | `.pdf` |
| `/download-report` | Daily Payout Audit Standalone HTML Report | `.html` |
| `/api/telegram-sebi/download-excel`| 10-Day Telegram & SEBI Audit Excel Tracker | `.xlsx` |
| `/api/telegram-sebi/download-csv` | 10-Day Telegram & SEBI Audit CSV Report | `.csv` |

---

## 🔍 6. Audit Modules & Risk Logic

### Self-Transactions (2-Day Window Hierarchy)
- Creators who purchased their own products (`selfPayment == True`).
- Strict 2-day allowed window: **27 Aug (Today)** $\to$ **26 Aug (Yesterday)** $\to$ **25 Aug (Window Buffer)**.
- Within each day, creators are sequenced **from Highest Self-Transaction Amount to Lowest**.
- Visual date divider banners segment each day's violations.

### Telegram Integration (`vig/{productId}`) & SEBI Verification
- Identifies products utilizing Telegram delivery (`vig/` product URLs or `integratedGroup == True`).
- Filters payout settlements $\ge$ ₹1,000.
- Cross-references Creator ID against `sebi_master_creators.xlsx`:
  - **Match Found**: `SEBI Registered: Yes` | Status: `Verified` | Review: `Normal`.
  - **No Match**: `SEBI Registered: No` | Status: `Not Verified` | Review: `Manual Review Required` | Action: `HOLD`.

### Missing Content Deliverables (`noLink`)
- Inspects downloadable digital courses/files. Flagged if no deliverable link or module is attached.

---

## 📁 7. Repository Structure

```
cosmofeed_settlement/
├── .github/
│   └── workflows/
│       └── daily_audit.yml            # Automated daily audit workflow (09:00 AM IST)
├── data/
│   ├── non_sebi_creators_ledger.json  # Canonical persistent non-SEBI JSON ledger (Until 5 Sep)
│   ├── non_sebi_creators_cumulative.xlsx # Multi-sheet formatted Excel workbook
│   ├── non_sebi_creators_cumulative.csv  # Flat CSV export of deduplicated non-SEBI creators
│   ├── sebi_master_creators.xlsx      # Official verified SEBI master registry
│   └── sebi_master_creators.json      # Fast JSON lookup index of SEBI creators
├── reports/
│   ├── data.json                      # Daily audit dataset (1,831 creators)
│   ├── Cosmofeed_Payout_Audit_Report.pdf # Executive daily audit PDF
│   ├── payout_audit_report.html       # Standalone daily HTML audit report
│   ├── Manager_Submission_Non_SEBI_Report.pdf  # Manager submission PDF with sign-off
│   ├── Manager_Submission_Non_SEBI_Report.html # Manager submission HTML report
│   ├── telegram_sebi_10day_report.xlsx # 10-day Telegram & SEBI Excel report
│   ├── telegram_sebi_10day_report.csv  # 10-day Telegram & SEBI CSV report
│   ├── slack_report.txt               # Formatted Slack Markdown executive brief
│   └── daily_automation.log           # Timestamped execution log of daily pipeline
├── tests/
│   ├── test_non_sebi_manager.py       # Deduplication and export unit tests
│   ├── test_sebi_scraper.py           # SEBI scraper unit tests
│   └── test_telegram_sebi_verifier.py # Telegram/SEBI verification unit tests
├── index.html                         # Futuristic Gemini-style web dashboard
├── server.py                          # Local HTTP server with all download endpoints
├── non_sebi_manager.py                # Deduplication, cumulative volume, and report engine
├── daily_automation.py                # Standalone end-to-end automation runner
├── telegram_sebi_verifier.py          # Telegram detection & SEBI matcher
├── build_data_from_audit.py           # Data builder & pipeline coordinator
├── generate_report.py                 # HTML, PDF, and Slack report generator
├── generate_pdf.py                    # ReportLab executive PDF builder
├── payout_audit_agent.py              # Settlement API fetcher & Kundli analyzer
├── run_daily_audit.bat                # Windows double-clickable execution batch file
├── setup_daily_task.ps1               # Windows Task Scheduler registration script
└── README.md                          # Documentation and handbook
```

---

## 🚀 8. Setup & Quick Start Guide

### Prerequisites
- Python 3.10 or higher.
- Install dependencies:
  ```bash
  pip install requests pandas openpyxl reportlab
  ```

### Running the Dashboard Locally
1. Start the server:
   ```bash
   python server.py
   ```
2. Open your browser to **`http://localhost:8000/`**.

### Running the Daily Audit Manually
To execute the complete daily pipeline immediately:
```bash
python daily_automation.py
```
Or double-click `run_daily_audit.bat` on Windows.

### Scheduling on Windows Task Scheduler
To schedule the audit to run automatically every morning at **09:00 AM IST**:
```powershell
powershell -ExecutionPolicy Bypass -File .\setup_daily_task.ps1
```

---

## 🐙 9. GitHub Actions & CI/CD Deployment

The repository is configured with automated GitHub Actions in [`.github/workflows/daily_audit.yml`](file:///c:/Users/Mindf/cosmofeed_settlement/.github/workflows/daily_audit.yml):
- **Schedule**: Every day at `30 3 * * *` (03:30 AM UTC = **09:00 AM IST**).
- **Environment Secrets** (Optional for live scraping):
  - `COSMOFEED_TOKEN`: Bearer token for Cosmofeed admin panel.
  - `COSMOFEED_REFRESH_TOKEN`: Refresh token for session renewal.
- **Git Pushback**: Automatically commits and pushes updated reports and ledger back to `main`.
- **GitHub Pages**: Automatically deploys the latest version to GitHub Pages.

---

*Cosmofeed Compliance Operations · Authorized Audit System Valid Through 05-September-2026*
