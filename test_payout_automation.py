#!/usr/bin/env python3
"""
Test Suite for Product Link Validation & Payout Automation System
===================================================================
Covers all 10 mandatory test scenarios:
  1. Payout False + valid product link
  2. Payout False + missing product link
  3. Payout True + warning remark
  4. Payout True + no remark
  5. Repeated issue
  6. New issue
  7. vig/product_id (Telegram exclusion)
  8. API failure (API_VALIDATION_FAILED)
  9. Invalid product ID
 10. Duplicate notification prevention
"""

import os
import sys
import unittest
import tempfile
import json

import product_validator
from issue_tracker import IssueTracker, normalize_issue_text
from whatsapp_notifier import WhatsAppNotifier, format_on_hold_message, format_approved_message
import payout_automation
from payout_automation import process_payout_row


class TestPayoutAutomation(unittest.TestCase):
    def setUp(self):
        payout_automation.PRODUCT_VAL_CACHE.clear()
        # Create temp history and log files for isolated testing
        self.tmp_dir = tempfile.mkdtemp()
        self.history_file = os.path.join(self.tmp_dir, "test_issue_history.json")
        self.log_file = os.path.join(self.tmp_dir, "test_notification_log.json")
        
        self.issue_tracker = IssueTracker(history_filepath=self.history_file)
        self.notifier = WhatsAppNotifier(log_filepath=self.log_file)

    def test_case_1_payout_false_valid_product_link(self):
        """1. Payout False + valid product link -> ON HOLD with valid link status."""
        row = {
            "creatorId": "cr_001",
            "creatorName": "Alice",
            "phone": "+919876543210",
            "productName": "Valid E-book",
            "productId": "66b33dc602e939001355091d",
            "payoutStatus": False,
            "issue": "Kyc pending",
            "remarks": "Please update PAN document."
        }
        mock_api = {
            "pageData": {
                "unlockedFiles": ["https://s3.amazonaws.com/book.pdf"]
            }
        }
        res = process_payout_row(row, issue_tracker=self.issue_tracker, notifier=self.notifier, mock_api_response=mock_api)
        
        self.assertEqual(res["validationStatus"], "LINK_ATTACHED")
        self.assertEqual(res["payoutStatus"], "ON HOLD")
        self.assertFalse(res["payoutApproved"])
        self.assertIn("HOLD", res["generatedMessage"])
        self.assertIn("Valid E-book", res["generatedMessage"])

    def test_case_2_payout_false_missing_product_link(self):
        """2. Payout False + missing product link -> LINK_MISSING status and ON HOLD."""
        row = {
            "creatorId": "cr_002",
            "creatorName": "Bob",
            "phone": "+919876543211",
            "productName": "Empty Product",
            "productId": "67b3f39cae18900013e0aa95",
            "payoutStatus": False,
            "remarks": "No link attached."
        }
        mock_api = {"pageData": {"products": []}}
        res = process_payout_row(row, issue_tracker=self.issue_tracker, notifier=self.notifier, mock_api_response=mock_api)

        self.assertEqual(res["validationStatus"], "LINK_MISSING")
        self.assertEqual(res["payoutStatus"], "ON HOLD")
        self.assertIn("Product link missing", res["issue"])

    def test_case_3_payout_true_warning_remark(self):
        """3. Payout True + warning remark -> APPROVED with remarks in message."""
        row = {
            "creatorId": "cr_003",
            "creatorName": "Charlie",
            "phone": "+919876543212",
            "productName": "Trading Masterclass",
            "productId": "657c65fb4c5340001e5b3877",
            "payoutStatus": True,
            "remarks": "Minor discrepancy in bank name, approved for today."
        }
        mock_api = {"pageData": {"redirectSuccessURL": "https://drive.google.com/folder"}}
        res = process_payout_row(row, issue_tracker=self.issue_tracker, notifier=self.notifier, mock_api_response=mock_api)

        self.assertEqual(res["payoutStatus"], "APPROVED")
        self.assertTrue(res["payoutApproved"])
        self.assertIn("Remarks:", res["generatedMessage"])
        self.assertIn("Minor discrepancy in bank name", res["generatedMessage"])

    def test_case_4_payout_true_no_remark(self):
        """4. Payout True + no remark -> APPROVED without empty Remarks section."""
        row = {
            "creatorId": "cr_004",
            "creatorName": "David",
            "phone": "+919876543213",
            "productName": "Design Assets",
            "productId": "661d500ed78584001a489569",
            "payoutStatus": True,
            "remarks": ""
        }
        mock_api = {"pageData": {"unlockedFiles": ["https://s3.amazonaws.com/assets.zip"]}}
        res = process_payout_row(row, issue_tracker=self.issue_tracker, notifier=self.notifier, mock_api_response=mock_api)

        self.assertEqual(res["payoutStatus"], "APPROVED")
        self.assertNotIn("Remarks:", res["generatedMessage"])

    def test_case_6_new_issue(self):
        """6. New issue -> isRepeatedIssue is False, no warning header."""
        row = {
            "creatorId": "cr_006",
            "creatorName": "Eva",
            "phone": "+919876543214",
            "productName": "Course 1",
            "productId": "662bc0195de1120013b2a193",
            "payoutStatus": False,
            "issue": "First Time Violation",
            "reviewDate": "2026-08-10"
        }
        mock_api = {"pageData": {"redirectSuccessURL": "https://example.com"}}
        res = process_payout_row(row, issue_tracker=self.issue_tracker, notifier=self.notifier, mock_api_response=mock_api)
        self.assertFalse(res["isRepeatedIssue"])
        self.assertEqual(res["warning"], "")

    def test_case_5_repeated_issue(self):
        """5. Repeated issue -> isRepeatedIssue is True with warning header."""
        row1 = {
            "creatorId": "cr_005",
            "creatorName": "Eva",
            "phone": "+919876543214",
            "productName": "Course 1",
            "productId": "662bc0195de1120013b2a193",
            "payoutStatus": False,
            "issue": "Copyright Infringement",
            "reviewDate": "2026-08-10"
        }
        mock_api = {"pageData": {"redirectSuccessURL": "https://example.com"}}
        process_payout_row(row1, issue_tracker=self.issue_tracker, notifier=self.notifier, mock_api_response=mock_api)

        row2 = {
            "creatorId": "cr_005",
            "creatorName": "Eva",
            "phone": "+919876543214",
            "productName": "Course 2",
            "productId": "662bc0195de1120013b2a193",
            "payoutStatus": False,
            "issue": "copyright infringement!",
            "reviewDate": "2026-08-11"
        }
        res2 = process_payout_row(row2, issue_tracker=self.issue_tracker, notifier=self.notifier, mock_api_response=mock_api)
        self.assertTrue(res2["isRepeatedIssue"])
        self.assertIn("Warning: The same/similar issue has been observed previously", res2["warning"])

    def test_case_7_vig_product_id_telegram_exception(self):
        """7. vig/{product_id} -> TELEGRAM_VIG_EXCLUDED, must NOT be flagged as missing link."""
        row = {
            "creatorId": "cr_007",
            "creatorName": "Frank",
            "phone": "+919876543216",
            "productName": "Telegram Signals Group",
            "productId": "67a77fdaaceb2400138be70b",
            "productUrl": "https://superprofile.bio/vig/67a77fdaaceb2400138be70b",
            "productType": "vig",
            "payoutStatus": True
        }
        res = process_payout_row(row, issue_tracker=self.issue_tracker, notifier=self.notifier, mock_api_response=None)

        self.assertEqual(res["validationStatus"], "TELEGRAM_VIG_EXCLUDED")
        self.assertTrue(res["linkAttached"])

    def test_case_8_api_failure(self):
        """8. API failure -> API_VALIDATION_FAILED, must NOT assume missing link."""
        row = {
            "creatorId": "cr_008",
            "creatorName": "Grace",
            "phone": "+919876543217",
            "productName": "Premium Ebook",
            "productId": "66b33dc602e939001355091d",
            "payoutStatus": True
        }
        mock_api_err = {"__error__": "HTTP 504 Gateway Timeout"}
        res = process_payout_row(row, issue_tracker=self.issue_tracker, notifier=self.notifier, mock_api_response=mock_api_err)

        self.assertIn(res["validationStatus"], ("API_VALIDATION_FAILED", "MANUAL_REVIEW_REQUIRED"))
        self.assertIsNone(res["linkAttached"])

    def test_case_9_invalid_product_id(self):
        """9. Invalid product ID -> INVALID_PRODUCT validation status."""
        row = {
            "creatorId": "cr_009",
            "creatorName": "Henry",
            "phone": "+919876543218",
            "productName": "Invalid Item",
            "productId": "",
            "productUrl": "",
            "payoutStatus": False
        }
        res = process_payout_row(row, issue_tracker=self.issue_tracker, notifier=self.notifier, mock_api_response=None)

        self.assertEqual(res["validationStatus"], "INVALID_PRODUCT")

    def test_case_10_duplicate_notification(self):
        """10. Duplicate notification -> Second notification call is skipped."""
        row = {
            "creatorId": "cr_010",
            "creatorName": "Irene",
            "phone": "+919876543219",
            "productName": "VIP Group",
            "productId": "67b3f39cae18900013e0aa95",
            "payoutStatus": False,
            "issue": "Missing pan",
            "reviewDate": "2026-08-11"
        }
        mock_api = {"pageData": {"unlockedFiles": ["file.pdf"]}}
        
        # First send
        res1 = process_payout_row(row, issue_tracker=self.issue_tracker, notifier=self.notifier, mock_api_response=mock_api)
        self.assertTrue(res1["whatsappStatus"]["success"])
        self.assertFalse(res1["whatsappStatus"]["isDuplicate"])

        # Second send (same day, same creator, same product, same issue)
        res2 = process_payout_row(row, issue_tracker=self.issue_tracker, notifier=self.notifier, mock_api_response=mock_api)
        self.assertFalse(res2["whatsappStatus"]["success"])
        self.assertTrue(res2["whatsappStatus"]["isDuplicate"])


if __name__ == "__main__":
    unittest.main()
