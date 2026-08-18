#!/usr/bin/env python3
"""
Repeated Issue Tracker Module
=============================
Maintains compliance issue history per creator.
Normalizes issue descriptions (case, spaces, punctuation) to detect repeated violations.
Generates standard compliance warning blocks for repeated issues.
"""

import os
import re
import json
import datetime

REPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)
HISTORY_FILE = os.path.join(REPORTS_DIR, "issue_history.json")

WARNING_TEXT = (
    "⚠️ Warning: The same/similar issue has been observed previously.\n"
    "Please ensure that the issue is not repeated in future submissions, "
    "as continued repetition may result in stricter compliance action."
)


def normalize_issue_text(issue_str):
    """Normalize issue text for robust fuzzy/exact matching across submissions."""
    if not issue_str:
        return ""
    text = str(issue_str).lower().strip()
    # Remove punctuation characters except alphanumerics and spaces
    text = re.sub(r"[^\w\s]", "", text)
    # Collapse multiple whitespaces
    text = re.sub(r"\s+", " ", text)
    return text.strip()


class IssueTracker:
    def __init__(self, history_filepath=HISTORY_FILE):
        self.filepath = history_filepath
        self.history = self._load_history()

    def _load_history(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_history(self):
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self.history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Warning: Failed to save issue history: {e}")

    def check_issue(self, creator_key, issue_text):
        """
        Check if an issue or substantially similar issue occurred previously for the given creator.
        Returns tuple: (is_repeated: bool, warning_message: str, previous_occurrences: int)
        """
        if not creator_key or not issue_text:
            return False, "", 0

        norm_key = str(creator_key).strip().lower()
        norm_issue = normalize_issue_text(issue_text)

        if not norm_issue:
            return False, "", 0

        creator_records = self.history.get(norm_key, [])
        occurrences = 0

        for rec in creator_records:
            past_norm = normalize_issue_text(rec.get("issue"))
            if past_norm and (norm_issue == past_norm or norm_issue in past_norm or past_norm in norm_issue):
                occurrences += 1

        is_repeated = occurrences > 0
        warning = WARNING_TEXT if is_repeated else ""
        return is_repeated, warning, occurrences

    def record_issue(self, creator_key, issue_text, product_id="", review_date="", payout_status=False, remarks=""):
        """Record a new compliance issue event for a creator."""
        if not creator_key or not issue_text:
            return

        norm_key = str(creator_key).strip().lower()
        if norm_key not in self.history:
            self.history[norm_key] = []

        entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "reviewDate": review_date or datetime.date.today().isoformat(),
            "issue": issue_text,
            "normalizedIssue": normalize_issue_text(issue_text),
            "productId": product_id,
            "payoutStatus": payout_status,
            "remarks": remarks
        }
        self.history[norm_key].append(entry)
        self._save_history()
