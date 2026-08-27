"""
Unit tests for Telegram Integration & SEBI Verification enhancement.
Covers all 8 test scenarios specified in the requirements:
  - Test 1: Settlement Below ₹1,000 (Excluded)
  - Test 2: Settlement Exactly ₹1,000 (Included)
  - Test 3: Telegram + SEBI Verified (Yes / —, Verified)
  - Test 4: Telegram + Not Found (— / No, Not Verified, Manual Review)
  - Test 5: Non-Telegram (Telegram = NO, no SEBI flag)
  - Test 6: Duplicate Creator handling & volume aggregation
  - Test 7: Product API / Validation Failure handling (not No)
  - Test 8: SEBI Master Excel Failure handling (not No)
"""

import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import telegram_sebi_verifier as verifier


class TestTelegramSEBIVerifier(unittest.TestCase):

    def setUp(self):
        self.mock_master = {
            "67bff2a289232b0013343cec": {
                "creator_id": "67bff2a289232b0013343cec",
                "ra_name": "RAMPRASAD OMPRAKASH MUNDADA",
                "sebi_reg_no": "INH000010690",
                "email": "maxprocapitaladvisory@gmail.com",
                "product_type": "TGI"
            },
            "61e996f678f4fa74e5da637d": {
                "creator_id": "61e996f678f4fa74e5da637d",
                "ra_name": "Aditya Gate",
                "sebi_reg_no": "INH000019099",
                "email": "sadityagatep@gmail.com",
                "product_type": "TGI"
            }
        }

    # -------------------------------------------------------------
    # Test 1: Settlement Below ₹1,000
    # -------------------------------------------------------------
    def test_01_settlement_below_1000_excluded(self):
        """Settlements < ₹1,000 are excluded from Telegram + SEBI check."""
        row = {
            "settlementId": "s_below_1000",
            "creatorId": "67bff2a289232b0013343cec",
            "payoutAmount": 999.0,
            "productUrl": "https://superprofile.bio/vig/6a5fa35a0f3a3c0014f55b1d",
            "productType": "vig"
        }
        res = verifier.verify_single_settlement(row, self.mock_master)
        self.assertFalse(res["telegramEligible"])
        self.assertFalse(res["telegramIntegration"])
        self.assertEqual(res["sebiRegisteredYes"], "—")
        self.assertEqual(res["sebiRegisteredNo"], "—")
        self.assertEqual(res["sebiVerificationStatus"], "Not Applicable")
        self.assertEqual(res["sebiReviewStatus"], "Normal")

    # -------------------------------------------------------------
    # Test 2: Settlement Exactly ₹1,000
    # -------------------------------------------------------------
    def test_02_settlement_exactly_1000_included(self):
        """Settlement of exactly ₹1,000 is eligible for Telegram + SEBI check."""
        row = {
            "settlementId": "s_exact_1000",
            "creatorId": "67bff2a289232b0013343cec",
            "payoutAmount": 1000.0,
            "productUrl": "https://superprofile.bio/vig/6a5fa35a0f3a3c0014f55b1d",
            "productType": "vig"
        }
        res = verifier.verify_single_settlement(row, self.mock_master)
        self.assertTrue(res["telegramEligible"])
        self.assertTrue(res["telegramIntegration"])

    # -------------------------------------------------------------
    # Test 3: Telegram + SEBI Verified
    # -------------------------------------------------------------
    def test_03_telegram_and_sebi_verified(self):
        """Telegram creator with Creator ID in SEBI master list -> SEBI Yes, Verified."""
        row = {
            "settlementId": "s_verified",
            "creatorId": "67bff2a289232b0013343cec",
            "payoutAmount": 25000.0,
            "productUrl": "https://superprofile.bio/vig/6a5fa35a0f3a3c0014f55b1d",
            "productType": "vig"
        }
        res = verifier.verify_single_settlement(row, self.mock_master)
        self.assertTrue(res["telegramIntegration"])
        self.assertEqual(res["sebiRegisteredYes"], "Yes")
        self.assertEqual(res["sebiRegisteredNo"], "—")
        self.assertEqual(res["sebiVerificationStatus"], "Verified")
        self.assertEqual(res["sebiRegistrationNumber"], "INH000010690")
        self.assertEqual(res["sebiReviewStatus"], "Normal")

    # -------------------------------------------------------------
    # Test 4: Telegram + Not Found in SEBI Master List
    # -------------------------------------------------------------
    def test_04_telegram_not_found_in_sebi_list(self):
        """Telegram creator NOT found in SEBI master list -> SEBI No, Not Verified, Manual Review."""
        row = {
            "settlementId": "s_unverified",
            "creatorId": "999999999999999999999999",
            "payoutAmount": 25000.0,
            "productUrl": "https://superprofile.bio/vig/6a5fa35a0f3a3c0014f55b1d",
            "productType": "vig"
        }
        res = verifier.verify_single_settlement(row, self.mock_master)
        self.assertTrue(res["telegramIntegration"])
        self.assertEqual(res["sebiRegisteredYes"], "—")
        self.assertEqual(res["sebiRegisteredNo"], "No")
        self.assertEqual(res["sebiVerificationStatus"], "Not Verified")
        self.assertEqual(res["sebiReviewStatus"], "Manual Review Required")

    # -------------------------------------------------------------
    # Test 5: Non-Telegram Creator
    # -------------------------------------------------------------
    def test_05_non_telegram_product(self):
        """Non-Telegram products (regular page or course) are not flagged."""
        row = {
            "settlementId": "s_non_tele",
            "creatorId": "67bff2a289232b0013343cec",
            "payoutAmount": 25000.0,
            "productUrl": "https://superprofile.bio/vp/6a5fa35a0f3a3c0014f55b1d",
            "productType": "page"
        }
        res = verifier.verify_single_settlement(row, self.mock_master)
        self.assertFalse(res["telegramIntegration"])
        self.assertEqual(res["sebiRegisteredYes"], "—")
        self.assertEqual(res["sebiRegisteredNo"], "—")
        self.assertEqual(res["sebiVerificationStatus"], "Not Applicable")
        self.assertEqual(res["sebiReviewStatus"], "Normal")

    # -------------------------------------------------------------
    # Test 6: Duplicate Creator / Multi-Settlement
    # -------------------------------------------------------------
    def test_06_duplicate_creator_volume_aggregation(self):
        """Same Creator ID in multiple settlements is tracked accurately without duplicates in 10-day log."""
        settlements = [
            {
                "settlementId": "s1",
                "creatorId": "61e996f678f4fa74e5da637d",
                "payoutAmount": 5000.0,
                "productUrl": "https://superprofile.bio/vig/prod1",
                "productType": "vig"
            },
            {
                "settlementId": "s2",
                "creatorId": "61e996f678f4fa74e5da637d",
                "payoutAmount": 15000.0,
                "productUrl": "https://superprofile.bio/vig/prod1",
                "productType": "vig"
            }
        ]
        verified_rows, stats = verifier.verify_all_settlements(settlements)
        self.assertEqual(len(verified_rows), 2)
        self.assertEqual(stats["uniqueTelegramCreators"], 1)
        self.assertEqual(stats["telegramCount"], 2)

    # -------------------------------------------------------------
    # Test 7: Product API / Validation Failure Handling
    # -------------------------------------------------------------
    def test_07_product_validation_failure_not_marked_no(self):
        """Failure to retrieve product details sets Unable to Validate / Manual Review, not No."""
        row = {
            "settlementId": "s_err",
            "creatorId": "67bff2a289232b0013343cec",
            "payoutAmount": 5000.0,
            "productUrl": "https://superprofile.bio/vig/some_pid",
            "productType": "vig"
        }
        res = verifier.verify_single_settlement(row, self.mock_master, sebi_load_error="Network timeout")
        self.assertEqual(res["sebiVerificationStatus"], "Unable to Validate")
        self.assertEqual(res["sebiRegisteredNo"], "—")
        self.assertEqual(res["sebiReviewStatus"], "Manual Review Required")

    # -------------------------------------------------------------
    # Test 8: SEBI Excel Master List Failure
    # -------------------------------------------------------------
    def test_08_sebi_excel_failure_handling(self):
        """When SEBI master list fails to load, records are marked Unable to Validate, not No."""
        row = {
            "settlementId": "s_missing_master",
            "creatorId": "67bff2a289232b0013343cec",
            "payoutAmount": 5000.0,
            "productUrl": "https://superprofile.bio/vig/pid123",
            "productType": "vig"
        }
        res = verifier.verify_single_settlement(row, {}, sebi_load_error="Excel file missing or invalid")
        self.assertEqual(res["sebiVerificationStatus"], "Unable to Validate")
        self.assertEqual(res["sebiRegisteredYes"], "—")
        self.assertEqual(res["sebiRegisteredNo"], "—")
        self.assertEqual(res["sebiReviewStatus"], "Manual Review Required")


if __name__ == "__main__":
    unittest.main()
