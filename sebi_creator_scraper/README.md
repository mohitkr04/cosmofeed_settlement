# SEBI Registered Creator Discovery & Data Scraping

An isolated automation workflow for discovering and extracting all **SEBI-registered creators** across the Cosmofeed ecosystem into Excel and CSV reports.

> **Isolation Guarantee:** This module is completely independent from the settlement auditing and payout review workflows. It does not modify, import, or alter any settlement calculation or audit logic.

---

## Features

1. **Initial Creator Harvesting**:
   - Automatically harvests all existing Creator IDs from `reports/*.json` (`audit_*.json`, `data.json`, `self_txn_*.json`), pre-loading over 4,400+ unique creators without unnecessary initial API calls.
   - Optionally fetches live pending settlements from `/IDgetSettlements`.

2. **Recursive Connected-ID Exploration**:
   - For every creator, queries `/getCreatorKundli?type=userId&value={creator_id}` to collect profile attributes:
     - `Creator ID`
     - `Username`
     - `Email`
     - `Onboarded By`
     - `Onboarding Vertical`
   - Recursively extracts **All Connected IDs** and enqueues them for complete discovery.

3. **Comprehensive Product Inspection (Including VIG/Telegram)**:
   - Queries creator's products via `/getCreatorKundli?requestedAction=lastHundredSoldProducts`.
   - Inspects **ALL** product types:
     - Normal payment pages (`vp`, `page`, `ps`)
     - **VIG / Telegram products** (`vig`, `integratedGroup`)
     - Courses (`course`)
   - Product-level caching prevents duplicate API requests across creators sharing products.

4. **SEBI Registration Detection**:
   - Identifies the official indicator: `Registered with SEBI (INH000019099)` or `Registered with SEBI (<REG_NO>)`.
   - Supports SEBI registration number formats (`INH\d{9}`, `INA\d{9}`, etc.) and badge references (`checklist-yellow.png`).
   - Extracts exact registration number and auditable contextual evidence snippets.
   - Strictly sets `SEBI Registered = YES` only when confirmed evidence is present (never based on assumptions).

5. **Deduplication & Multi-Source Preservation**:
   - Exactly one unique record per Creator ID in the master dataset.
   - Merges discovery sources (e.g. `Audit (audit_2026-08-12.json), Settlement Review, Connected Creator ID (...)`).

6. **Resumability & Error Isolation**:
   - Periodic atomic checkpointing to `reports/sebi_scraper_checkpoint.json`.
   - Can resume seamlessly via `--resume` after pausing or interruption.
   - Single creator API failures do not abort the scraping process.

7. **Multi-Sheet Excel & Normalized CSV Output**:
   - `sebi_registered_creators.xlsx`:
     - **Sheet 1 — SEBI Registered Creators**: One unique row per creator with full profile metadata.
     - **Sheet 2 — SEBI Evidence - Products**: Auditable product-level evidence table.
   - `sebi_registered_creators.csv`: Normalized unique creator dataset.

---

## Usage

### 1. Quick Test Run (e.g. first 5 creators)
```bash
python -m sebi_creator_scraper.runner --limit 5
```

### 2. Full Run with Checkpointing
```bash
python -m sebi_creator_scraper.runner
```

### 3. Resume an Interrupted Run
```bash
python -m sebi_creator_scraper.runner --resume
```

### 4. Include Live Settlements from Admin Review
```bash
python -m sebi_creator_scraper.runner --include-settlements
```

### 5. Custom Output Paths
```bash
python -m sebi_creator_scraper.runner --limit 50 --output-excel my_report.xlsx --output-csv my_report.csv
```

---

## Running Unit Tests

Run the automated test suite covering all 7 requirement test cases:
```bash
python -m unittest tests/test_sebi_scraper.py
```

---

## Security & Credentials

- Never commit access or refresh tokens to source control.
- Credentials are automatically loaded from `.env` (`COSMOFEED_TOKEN`, `COSMOFEED_REFRESH_TOKEN`) or environment variables.
- All tokens are masked in logs and reports.
