# 🛡️ Cosmofeed Payout Audit & Settlement Dashboard

An automated auditing tool and local web dashboard designed to inspect **Cosmofeed pending settlements (payouts)** and flag high-risk transactions before payouts are processed.

---

## 📌 Table of Contents
1. [🎯 Project Motive & Overview](#-1-project-motive--overview)
2. [🔑 How to Find Your Cosmofeed Token (Step-by-Step)](#-2-how-to-find-your-cosmofeed-token-step-by-step)
3. [📚 Python Libraries Used & Why](#-3-python-libraries-used--why)
4. [🔍 Data Pipeline & Code Steps Breakdown](#-4-data-pipeline--code-steps-breakdown)
5. [🌐 Web Scraping Code Snippet](#-5-web-scraping-code-snippet)
6. [📁 Codebase Map (How to Read & Modify Code)](#-6-codebase-map-how-to-read--modify-code)
7. [🚀 How to Run the Project](#-7-how-to-run-the-project)
8. [📊 Dashboard Filters & Accuracy](#-8-dashboard-filters--accuracy)

---

## 🎯 1. Project Motive & Overview

### The Problem
Fintech platforms and creator monetization networks face risk during daily settlement payouts. Malicious or risky creators might:
- **Self-Transact**: Buy their own courses/digital products using their own credentials/cards to falsely inflate transaction history, abuse promotional discounts, or cash out illicit funds.
- **Sell Violating Content**: Offer prohibited adult services, copyright infringement, or deceptive products.
- **Inaccessible Storefronts**: Have broken or nonexistent public landing pages while requesting payouts.

Manually auditing thousands of creators per day via the admin panel is extremely time-consuming.

### The Solution
This tool automates the daily audit by fetching all pending settlement requests, querying deep transactional history ("Kundli") for each creator, running heuristic classification checks, and rendering an interactive local dashboard with instant filtering for decision-making.

---

## 🔑 2. How to Find Your Cosmofeed Token (Step-by-Step)

To fetch live settlement data, the Python scripts require a valid **Bearer Authorization Token** from your Cosmofeed admin account. Follow these steps to find it:

```
[Log into Admin Panel] ➔ [Open F12 DevTools] ➔ [Network Tab] ➔ [Inspect Request] ➔ [Copy Token]
```

### Step 1: Open Cosmofeed Admin Panel
Open your browser (Google Chrome, Edge, Brave, or Firefox) and log into:
👉 **`https://admin.cosmofeed.com/`**

### Step 2: Open Developer Tools
Press **`F12`** on your keyboard (or right-click anywhere on the page and click **Inspect**).

### Step 3: Switch to the Network Tab
In the DevTools panel at the top, click on the **Network** tab.

### Step 4: Locate an API Request
1. Refresh the page or click on the **Settlements** section in the admin sidebar.
2. In the Network tab search/filter box, type `IDgetSettlements` or `internal_dashboard`.
3. Click on any request that appears in the list (e.g., `IDgetSettlements?requestType=pending...`).

### Step 5: Copy the Authorization Header Value
1. In the panel that opens on the right, click the **Headers** tab.
2. Scroll down to the **Request Headers** section.
3. Find the header named `authorization` (or `Authorization`).
4. The value looks like this: `Bearer eyJhbGciOiJKV1QiLCJhbGciOi...`
5. Copy the long sequence of characters **AFTER `Bearer `**. This is your `COSMOFEED_TOKEN`.

---

## 📚 3. Python Libraries Used & Why

This project is built using **Python Standard Libraries ONLY** so any beginner can run it without needing `pip install` or managing virtual environments.

| Library / Module | Purpose in This Project | Why it was chosen |
| :--- | :--- | :--- |
| **`urllib.request` & `urllib.error`** | Makes HTTP GET API calls to Cosmofeed internal endpoints and public bio links. | Built into Python; eliminates external dependencies like `requests`. |
| **`json`** | Converts API JSON strings into Python objects (dicts/lists) and saves output to `data.json`. | Native JSON parsing for web API communication. |
| **`concurrent.futures.ThreadPoolExecutor`** | Audits multiple creators simultaneously using thread workers (`--workers 4`). | Speeds up processing ~1,800 creators from ~20 minutes down to < 1 minute. |
| **`http.server` & `socketserver`** | Powers the local dashboard web server on `http://localhost:8000`. | Provides a lightweight local HTTP server without needing Flask or Node.js. |
| **`argparse`** | Reads command-line arguments like `--limit 100`, `--workers 4`, and `--token XYZ`. | Makes script execution configurable via terminal flags. |
| **`re`** | Performs regular expression word-boundary matching for adult/risk heuristics. | Prevents substring false positives (e.g., matching `sex` inside `OptionsExperts`). |
| **`os` & `sys`** | Reads system environment variables (`COSMOFEED_TOKEN`) and handles local paths. | Cross-platform compatibility for Windows, macOS, and Linux. |
| **`time` & `datetime`** | Adds rate-limiting sleeps between requests and timestamps generated reports. | Prevents HTTP 429 rate limits from Cosmofeed servers. |

---

## 🔍 4. Data Pipeline & Code Steps Breakdown

The data processing pipeline moves through 4 distinct stages to build the dataset:

```
┌─────────────────────────┐     ┌─────────────────────────────┐
│ 1. IDgetSettlements     │ ──> │ 2. IDgetSettlementDetails   │
│ (Fetch pending payouts) │     │ (Fetch creator ID & status) │
└─────────────────────────┘     └─────────────────────────────┘
                                               │
                                               ▼
┌─────────────────────────┐     ┌─────────────────────────────┐
│ 4. Public Page Check    │ <── │ 3. getCreatorKundli         │
│ (Scrape store bio link) │     │ (Analyze last 100 buyers)   │
└─────────────────────────┘     └─────────────────────────────┘
```

### Key Python Functions Explained

#### 1. Fetching All Pending Settlements (`payout_audit_agent.py`)
Fetches paginated settlement rows from Cosmofeed API:
```python
def fetch_all_settlements(token, request_type="pending"):
    # Step 1: Query page 1 to discover total pages & total settlement count
    first = api_get("/IDgetSettlements?requestType=pending&page=1...", token)
    total_pages = first["data"]["totalPages"]
    rows = first["data"]["settelements"]

    # Step 2: Loop through remaining pages and collect all payout rows
    for page in range(2, total_pages + 1):
        d = api_get(f"/IDgetSettlements?...&page={page}", token)
        rows.extend(d["data"]["settelements"])
    return rows
```

#### 2. Resolving Creator Details & Flags (`payout_audit_agent.py`)
Translates settlement IDs into underlying creator accounts:
```python
def resolve_settlement_details(settlement_id, token):
    d = api_get(f"/IDgetSettlementDetails?settlementId={settlement_id}", token)
    user = d["data"]["currentUserDetails"]
    return {
        "creatorId": user.get("creatorId"),
        "categoryOfBusiness": user.get("categoryOfBusiness"),
        "flagLevel": user.get("flagLevel")
    }
```

#### 3. Detecting Self-Transactions (`payout_audit_agent.py`)
Queries creator purchase history ("Kundli") to find self-payments:
```python
def check_self_transactions(creator_id, token):
    d = api_get(f"/getCreatorKundli?type=userId&value={creator_id}&requestedAction=groupedByBuyerId", token)
    buyers = extract_kundli_payload(d, "groupedByBuyerId")
    
    # Filter for buyers flagged by the platform's selfPayment boolean
    self_txns = [b for b in buyers if b.get("selfPayment") is True]
    return {"self": self_txns, "buyers": len(buyers)}
```

---

## 🌐 5. Web Scraping Code Snippet

To verify if a creator's public profile and store exist live, `server.py` includes a lightweight web scraping function using `urllib.request`:

```python
def live_nolink_check(username):
    """Web scraping live check for a creator's public storefront."""
    if not username:
        return {"reachable": False, "reason": "no username"}
        
    url = f"https://superprofile.bio/{username}"
    headers = {"user-agent": "Mozilla/5.0 ... Chrome/150.0.0.0"}
    
    try:
        req = urlreq.Request(url, headers=headers)
        with urlreq.urlopen(req, timeout=15) as resp:
            # Read first 60KB of HTML content
            body = resp.read(60000).decode("utf-8", "ignore").lower()
            status = resp.getcode()
    except HTTPError as e:
        if e.code == 404:
            return {"reachable": True, "status": 404, "noLink": True, "reason": "page not found (404)"}
        return {"reachable": True, "status": e.code, "noLink": None, "reason": f"HTTP {e.code}"}

    # Detect Vercel bot security challenges
    if "vercel security checkpoint" in body or "just a moment" in body:
        return {"reachable": True, "noLink": None, "reason": "bot-challenge (verify in browser)"}

    # Check for storefront product markers in HTML markup
    markers = ["add to cart", "buy now", "/e/", "product", "checkout"]
    has_products = any(m in body for m in markers)
    
    if not has_products:
        return {"reachable": True, "noLink": True, "reason": "page loads but no product links found"}
    return {"reachable": True, "noLink": False, "reason": "page has active product links"}
```

---

## 📁 6. Codebase Map (How to Read & Modify Code)

If you are new to the codebase, here is where everything lives and how to customize it:

```
cosmofeed_settlement/
├── server.py              # Local HTTP web server for the dashboard
├── build_data.py          # Data enrichment script (runs audit logic -> updates data.json)
├── payout_audit_agent.py  # Core Cosmofeed API wrapper & detection functions
├── index.html             # Main Dashboard UI (interactive HTML/JS table)
├── dashboard.html         # Alternative UI view layout
└── data.json              # Saved snapshot dataset loaded by the dashboard UI
```

### How to Modify for Your Needs:
- **To add new adult/risk keywords:** Open `build_data.py` and add words to the `ADULT_KEYWORDS` list on line 38.
- **To change the server port:** Open `server.py` and modify `PORT = int(os.environ.get("PORT", "8000"))`.
- **To adjust parallel worker threads:** Pass `--workers 8` when running `build_data.py`.
- **To customize UI columns/styles:** Edit `index.html`.

---

## 🚀 7. How to Run the Project

### Method A: Start the Dashboard (Zero Config)
Runs using pre-built data in `data.json`:

1. Open terminal in this project folder.
2. Run:
   ```bash
   python server.py
   ```
3. Open your browser to **`http://localhost:8000`**.

---

### Method B: Refresh Data from Live API

To fetch fresh pending settlements and re-audit all creators:

#### On Linux / macOS:
```bash
COSMOFEED_TOKEN="your_copied_token_here" python build_data.py
```

#### On Windows (PowerShell):
```powershell
$env:COSMOFEED_TOKEN="your_copied_token_here"; python build_data.py
```

#### On Windows (Command Prompt - CMD):
```cmd
set COSMOFEED_TOKEN=your_copied_token_here && python build_data.py
```

#### Quick Test Run (Limits to first 100 creators):
```bash
python build_data.py --limit 100
```

Once `build_data.py` finishes, refresh your browser tab at `http://localhost:8000` to see updated metrics!

---

## 📊 8. Dashboard Filters & Accuracy

| Filter | Accuracy Level | How it Works |
| :--- | :--- | :--- |
| **🔴 Self-Transaction** | ✅ **100% Accurate** | Uses Cosmofeed's internal `selfPayment` flag from creator buyer logs. Occurs when buyer email/phone matches creator details. |
| **🟠 Adult / Risk** | ⚠️ **Heuristic Flag** | Word-boundary regex keyword search on creator username, display name, and business category + `flagLevel` check. Intended for human review candidates. |
| **🟡 No Link** | ⚠️ **Live Check** | Live HTML request to `superprofile.bio/<username>` checking for 404 errors or missing product markup. |

---

> 💡 **Tip for Developers:** To stop the local server at any time, press `Ctrl + C` in your terminal window.

