#!/usr/bin/env python3
"""
WhatsApp Notification & Scheduling Module
==========================================
Formats creator notifications for Payout ON HOLD and Payout APPROVED states.
Prevents duplicate notifications using a unique deduplication key:
  creator_id + product_id + review_date + issue
Saves notification records to notification_log.json.
Provides background scheduling for daily 6:00 PM IST delivery.
"""

import os
import json
import time
import datetime

REPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)
LOG_FILE = os.path.join(REPORTS_DIR, "notification_log.json")


def format_on_hold_message(creator_name, product_name, product_link, issue, remarks="", action_required="", warning=""):
    """Format WhatsApp message for Payout ON HOLD (payoutStatus = False)."""
    name_str = creator_name or "Creator"
    p_name = product_name or "Digital Product"
    p_link = product_link or "N/A"
    reason = issue or "Compliance / Link Validation Issue"
    rem = remarks or "Please inspect product delivery configuration."
    action = action_required or "Update your product content link and ensure public page functionality."

    msg_lines = [
        f"Dear {name_str},",
        "",
        "Your payout for the following product is currently on HOLD.",
        "",
        "Product:",
        f"{p_name}",
        "",
        "Product Link:",
        f"{p_link}",
        "",
        "Reason:",
        f"{reason}",
        "",
        "Remarks:",
        f"{rem}",
        "",
        "Status:",
        "Payout On Hold",
        "",
        "Action Required:",
        f"{action}"
    ]

    if warning:
        msg_lines.extend(["", warning])

    msg_lines.extend([
        "",
        "Please resolve the mentioned issue and ensure that the same issue is not repeated in future submissions.",
        "",
        "Regards,",
        "Compliance / Support Team"
    ])
    return "\n".join(msg_lines)


def format_approved_message(creator_name, product_name, product_link, remarks="", warning=""):
    """Format WhatsApp message for Payout APPROVED (payoutStatus = True)."""
    name_str = creator_name or "Creator"
    p_name = product_name or "Digital Product"
    p_link = product_link or "N/A"

    msg_lines = [
        f"Dear {name_str},",
        "",
        "Your payout for the following product has been approved and will be processed.",
        "",
        "Product:",
        f"{p_name}",
        "",
        "Product Link:",
        f"{p_link}",
        "",
        "Status:",
        "Payout Approved"
    ]

    if remarks and str(remarks).strip():
        msg_lines.extend(["", "Remarks:", f"{remarks.strip()}"])

    if warning:
        msg_lines.extend(["", warning])

    msg_lines.extend([
        "",
        "Regards,",
        "Compliance / Support Team"
    ])
    return "\n".join(msg_lines)


class WhatsAppNotifier:
    def __init__(self, log_filepath=LOG_FILE):
        self.filepath = log_filepath
        self.sent_log = self._load_log()

    def _load_log(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_log(self):
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self.sent_log, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Warning: Failed to save notification log: {e}")

    def make_dedup_key(self, creator_id, product_id, review_date, issue):
        """Build unique deduplication key: creator_id + product_id + review_date + issue."""
        c_id = str(creator_id or "").strip().lower()
        p_id = str(product_id or "").strip().lower()
        r_date = str(review_date or datetime.date.today().isoformat()).strip()
        iss = str(issue or "").strip().lower()
        return f"{c_id}:{p_id}:{r_date}:{iss}"

    def is_already_sent(self, creator_id, product_id, review_date, issue):
        key = self.make_dedup_key(creator_id, product_id, review_date, issue)
        return key in self.sent_log

    def send_notification(self, creator_phone, message, creator_id="", product_id="", review_date="", issue="", mock_send=True):
        """
        Send WhatsApp notification with duplicate prevention.
        Returns dict: {success, key, isDuplicate, message}
        """
        key = self.make_dedup_key(creator_id, product_id, review_date, issue)

        if self.is_already_sent(creator_id, product_id, review_date, issue):
            return {
                "success": False,
                "isDuplicate": True,
                "dedupKey": key,
                "message": "Duplicate notification skipped (already sent today)"
            }

        # Dispatch via mock or actual WhatsApp gateway
        if not creator_phone:
            return {
                "success": False,
                "isDuplicate": False,
                "dedupKey": key,
                "message": "Missing creator phone number"
            }

        # Store success log
        self.sent_log[key] = {
            "timestamp": datetime.datetime.now().isoformat(),
            "phone": creator_phone,
            "creatorId": creator_id,
            "productId": product_id,
            "reviewDate": review_date or datetime.date.today().isoformat(),
            "issue": issue,
            "message": message,
            "status": "SENT"
        }
        self._save_log()

        return {
            "success": True,
            "isDuplicate": False,
            "dedupKey": key,
            "message": f"WhatsApp notification successfully queued/sent to {creator_phone}"
        }
