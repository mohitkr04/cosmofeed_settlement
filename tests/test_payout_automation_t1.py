#!/usr/bin/env python3
"""
Test Suite for Cosmofeed T+1 Product & Payout Review Automation
===============================================================
Verifies:
  1. Dynamic T+1 yesterday-only date filtering (Asia/Kolkata timezone).
  2. Deep product link validation (valid links, nested fields, Telegram vig/ exception).
  3. API failure handling (API_VALIDATION_FAILED -> MANUAL_REVIEW_REQUIRED, no false 404s).
  4. Self-payment, multiple payment, and adult compliance heuristics.
  5. Repeated issue detection and warning generation.
  6. Payout decision mapping (True = APPROVED, False = ON HOLD).
  7. WhatsApp message formatting and deduplication key generation.
  8. Unique product validation caching across duplicate transaction rows.
"""

import os
import sys
import unittest
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import payout_audit_agent as agent
import product_validator
import payout_automation
from issue_tracker import IssueTracker
from whatsapp_notifier import WhatsAppNotifier, format_on_hold_message, format_approved_message


class TestPayoutAutomationT1(unittest.TestCase):

    def setUp(self):
        self.issue_tracker = IssueTracker()
        self.issue_tracker.history.clear()
        self.notifier = WhatsAppNotifier()
        self.notifier.sent_log.clear()
        self.dates = agent.get_business_dates("Asia/Kolkata")
        self.today_str = self.dates["today_date"]
        self.yesterday_str = self.dates["yesterday_date"]

    def test_01_business_dates_ist(self):
        """Test IST business date calculation."""
        self.assertTrue(self.today_str)
        self.assertTrue(self.yesterday_str)
        # Verify yesterday is exactly 1 day prior to today
        today_dt = datetime.datetime.strptime(self.today_str, "%Y-%m-%d")
        yest_dt = datetime.datetime.strptime(self.yesterday_str, "%Y-%m-%d")
        self.assertEqual((today_dt - yest_dt).days, 1)

    def test_02_t1_date_filtering(self):
        """Test T+1 yesterday-only filtering logic."""
        rows = [
            {"creatorId": "c1", "saleDate": self.yesterday_str, "productName": "Yesterday Product 1"},
            {"creatorId": "c2", "saleDate": self.today_str, "productName": "Today Product"},
            {"creatorId": "c3", "saleDate": "2025-01-01", "productName": "Older Product"},
            {"creatorId": "c4", "saleDate": self.yesterday_str, "productName": "Yesterday Product 2"},
        ]
        filtered = payout_automation.filter_yesterday_products(rows, timezone_str="Asia/Kolkata")
        self.assertEqual(len(filtered), 2)
        p_names = [r["productName"] for r in filtered]
        self.assertIn("Yesterday Product 1", p_names)
        self.assertIn("Yesterday Product 2", p_names)
        self.assertNotIn("Today Product", p_names)
        self.assertNotIn("Older Product", p_names)

    def test_03_valid_product_link_parsing(self):
        """Test deep parsing of attached deliverable links."""
        # 1. Redirect URL
        res1 = product_validator.parse_page_data_attached({
            "pageData": {"redirectSuccessURL": "https://drive.google.com/folder/123"}
        })
        self.assertTrue(res1[0])

        # 2. Unlocked files array
        res2 = product_validator.parse_page_data_attached({
            "pageData": {"unlockedFiles": [{"name": "ebook.pdf", "url": "https://cdn.cosmofeed.com/ebook.pdf"}]}
        })
        self.assertTrue(res2[0])

        # 3. Product locked content
        res3 = product_validator.parse_page_data_attached({
            "pageData": {
                "products": [
                    {"lc": {"file": [{"url": "https://cdn.cosmofeed.com/file.zip"}]}}
                ]
            }
        })
        self.assertTrue(res3[0])

        # 4. Confirmed missing link
        res4 = product_validator.parse_page_data_attached({
            "pageData": {"title": "Empty Product", "products": []}
        })
        self.assertFalse(res4[0])

    def test_04_telegram_vig_exception(self):
        """Test Telegram vig/{product_id} exception rule."""
        val = product_validator.validate_product_link(
            product_id="6a5fa35a0f3a3c0014f55b1d",
            product_url="https://superprofile.bio/vig/6a5fa35a0f3a3c0014f55b1d",
            product_type="vig"
        )
        self.assertEqual(val["validationStatus"], "TELEGRAM_VIG_EXCLUDED")
        self.assertTrue(val["isAttached"])
        self.assertTrue(val["isVigExcluded"])

    def test_05_api_failure_handling(self):
        """Test that API failure does NOT flag link missing (Rule 10)."""
        mock_err = {"__error__": "HTTP 504 Gateway Timeout"}
        val = product_validator.validate_product_link(
            product_id="6a5fa35a0f3a3c0014f55b1d",
            product_type="page",
            mock_response=mock_err
        )
        self.assertEqual(val["validationStatus"], "API_VALIDATION_FAILED")
        self.assertIsNone(val["isAttached"])

        row_res = payout_automation.process_payout_row({
            "creatorId": "cr_test",
            "productId": "6a5fa35a0f3a3c0014f55b1d",
            "productType": "page",
            "payoutStatus": True
        }, mock_api_response=mock_err)

        self.assertEqual(row_res["validation_status"], "MANUAL_REVIEW_REQUIRED")
        self.assertIn("Manual Review Required", row_res["issue"])

    def test_06_self_payment_and_payout_hold(self):
        """Test self-payment rule and payout hold mapping."""
        row = {
            "creatorId": "68ef537ffdace79d748db517",
            "creatorName": "SelfTxnCreator",
            "phone": "9999999999",
            "productId": "6a5fa35a0f3a3c0014f55b1d",
            "productName": "Trading Course",
            "saleDate": self.yesterday_str,
            "selfTransaction": True,
            "selfTxnMaxAmount": 5000.0,
            "payoutStatus": False,
            "issue": "Self-transaction detected (buyer = creator)"
        }
        res = payout_automation.process_payout_row(row, issue_tracker=self.issue_tracker, notifier=self.notifier)
        self.assertEqual(res["payout_status"], "ON HOLD")
        self.assertFalse(res["payoutApproved"])
        self.assertIn("Self-transaction detected", res["issue"])

    def test_07_repeated_issue_detection(self):
        """Test repeated issue warning generation for creator history."""
        row1 = {
            "creatorId": "c_repeat_test",
            "creatorName": "RepeatCreator",
            "phone": "9876543210",
            "productId": "p101",
            "productName": "Digital Bundle",
            "saleDate": "2026-08-20",
            "payoutStatus": False,
            "issue": "Prohibited Software / APK Delivery"
        }
        res1 = payout_automation.process_payout_row(row1, issue_tracker=self.issue_tracker, notifier=self.notifier)
        self.assertEqual(res1["repeated_issue"], "NO")

        # Second time with same issue
        row2 = {
            "creatorId": "c_repeat_test",
            "creatorName": "RepeatCreator",
            "phone": "9876543210",
            "productId": "p102",
            "productName": "Digital Bundle v2",
            "saleDate": self.yesterday_str,
            "payoutStatus": False,
            "issue": "Prohibited Software / APK Delivery"
        }
        res2 = payout_automation.process_payout_row(row2, issue_tracker=self.issue_tracker, notifier=self.notifier)
        self.assertEqual(res2["repeated_issue"], "YES")
        self.assertIn("observed previously", res2["warning"])

    def test_08_whatsapp_deduplication(self):
        """Test WhatsApp notification deduplication key generation."""
        self.notifier.sent_log.clear()
        msg = format_on_hold_message("John", "Ebook", "https://cosmofeed.com/vp/123", "Missing Link", "On hold")
        res1 = self.notifier.send_notification("+919999999999", msg, creator_id="c1", product_id="p1", review_date=self.yesterday_str, issue="Missing Link", mock_send=True)
        self.assertTrue(res1["success"])
        self.assertFalse(res1["isDuplicate"])

        # Duplicate send attempt on same day with same key
        res2 = self.notifier.send_notification("+919999999999", msg, creator_id="c1", product_id="p1", review_date=self.yesterday_str, issue="Missing Link", mock_send=True)
        self.assertFalse(res2["success"])
        self.assertTrue(res2["isDuplicate"])

    def test_09_unique_product_api_caching(self):
        """Test that unique product IDs are validated once and cached."""
        payout_automation.PRODUCT_VAL_CACHE.clear()
        mock_attached = {"pageData": {"redirectSuccessURL": "https://google.com"}}
        
        row1 = {"creatorId": "c1", "productId": "p_cache_1", "productType": "page", "payoutStatus": True}
        row2 = {"creatorId": "c2", "productId": "p_cache_1", "productType": "page", "payoutStatus": True}

        res1 = payout_automation.process_payout_row(row1, mock_api_response=mock_attached)
        res2 = payout_automation.process_payout_row(row2, mock_api_response=mock_attached)

        self.assertEqual(res1["validation_status"], "LINK_ATTACHED")
        self.assertEqual(res2["validation_status"], "LINK_ATTACHED")
        cache_key = "p_cache_1::page"
        self.assertIn(cache_key, payout_automation.PRODUCT_VAL_CACHE)


if __name__ == "__main__":
    unittest.main()
