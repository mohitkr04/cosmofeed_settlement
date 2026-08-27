"""
Configuration and constants for SEBI Registered Creator Discovery.
"""

import os
import re

# Base URLs
ADMIN_BASE_URL = os.environ.get("ADMIN_BASE_URL", "https://admin.cosmofeed.com")
API_BASE_URL = os.environ.get("COSMOFEED_API_BASE", "https://prod.api.cosmofeed.com/api/internal_dashboard")
SUPERPROFILE_BASE_URL = "https://superprofile.bio"

# SEBI Reference Assets and Text Patterns
SEBI_BADGE_ICON_URL = "https://cdn.cosmofeed.com/assets/icons/checklist-yellow.png"
SEBI_BADGE_ICON_FILENAME = "checklist-yellow.png"

# Regex for exact badge/text format: "Registered with SEBI (INH000019099)"
# Captures both exact format and any variation of registration number
SEBI_EXACT_BADGE_PATTERN = re.compile(
    r"registered\s+with\s+sebi\s*\((?P<reg_no>[A-Z0-9]+)\)",
    re.IGNORECASE
)

# Standard SEBI Intermediary Registration Number formats:
# INH: Research Analyst (e.g., INH000019099)
# INA: Investment Adviser
# INZ: Stock Broker
# INM: Merchant Banker
# INP: Portfolio Manager
SEBI_REG_NUMBER_PATTERN = re.compile(
    r"\b(?P<reg_no>IN[A-Z0-9]{9,11})\b",
    re.IGNORECASE
)

# Broader text indicator when coupled with registration info
SEBI_TEXT_INDICATOR = re.compile(
    r"(?:sebi\s+registered|registered\s+with\s+sebi|sebi\s+reg(?:istration)?\.?\s*no\.?)",
    re.IGNORECASE
)

# Default output file paths
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
REPORTS_DIR = os.path.join(PROJECT_ROOT, "reports")

OUTPUT_EXCEL = os.path.join(PROJECT_ROOT, "sebi_registered_creators.xlsx")
OUTPUT_CSV = os.path.join(PROJECT_ROOT, "sebi_registered_creators.csv")
CHECKPOINT_FILE = os.path.join(REPORTS_DIR, "sebi_scraper_checkpoint.json")

# Network & Throttling
DEFAULT_REQUEST_TIMEOUT = 12.0
DEFAULT_MAX_RETRIES = 3
RATE_LIMIT_PER_SEC = 2.5
CHECKPOINT_INTERVAL = 25  # Save checkpoint every 25 creators


def mask_token(token: str) -> str:
    """Safely mask a token for logs or diagnostic display without exposing secrets."""
    if not token:
        return "<empty>"
    token_str = str(token).strip()
    if len(token_str) <= 8:
        return "***"
    return f"{token_str[:4]}...{token_str[-4:]}"
