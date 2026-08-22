#!/usr/bin/env python3
"""
Payout & Product Link Automation Orchestrator
=============================================
Processes creator payout review rows, performs production API product link validation,
applies the mandatory Telegram vig/{product_id} exception, tracks historical issues,
generates creator WhatsApp messages, enforces deduplication, and outputs structured results.
"""

import os
import sys
import json
import datetime
import argparse

import product_validator
import payout_audit_agent as agent
from issue_tracker import IssueTracker
from whatsapp_notifier import WhatsAppNotifier, format_on_hold_message, format_approved_message


PRODUCT_VAL_CACHE = {}


def process_payout_row(row, token=None, issue_tracker=None, notifier=None, mock_api_response=None):
    """
    Process a single payout/review row through the automated compliance pipeline.
    
    Returns standardized result dict with both canonical snake_case and legacy camelCase keys.
    """
    if issue_tracker is None:
        issue_tracker = IssueTracker()
    if notifier is None:
        notifier = WhatsAppNotifier()

    # 1. Extract & normalize row fields
    creator_id = str(row.get("creatorId") or row.get("creator_id") or row.get("username") or "").strip()
    creator_name = row.get("creatorName") or row.get("creator") or row.get("displayName") or row.get("username") or "Creator"
    creator_phone = row.get("phone") or row.get("phoneNumber") or row.get("PhoneNumber") or row.get("creatorPhoneNumber") or ""
    product_name = row.get("productName") or row.get("title") or row.get("productTitle") or "Digital Product"
    product_id = row.get("productId") or row.get("product_id") or ""
    product_url = row.get("productLink") or row.get("productUrl") or row.get("url") or ""
    product_type = row.get("productType") or row.get("product_type") or "page"
    sale_date = row.get("saleDate") or row.get("sale_date") or row.get("latestSelfTxnDate") or row.get("reviewDate") or datetime.date.today().isoformat()
    review_date = row.get("reviewDate") or row.get("review_date") or datetime.date.today().isoformat()
    raw_payout_status = row.get("payoutStatus") if "payoutStatus" in row else row.get("payout_status")
    
    # Standardize payout status boolean
    if isinstance(raw_payout_status, bool):
        payout_approved = raw_payout_status
    elif str(raw_payout_status).strip().lower() in ("true", "approved", "1", "yes"):
        payout_approved = True
    elif str(raw_payout_status).strip().lower() in ("false", "on hold", "on_hold", "0", "no"):
        payout_approved = False
    else:
        payout_approved = False

    issue = str(row.get("issue") or "").strip()
    remarks = str(row.get("remarks") or "").strip()

    # 2. Unique Product Link Validation with Cache (Section 20: Avoid Duplicate Product API Calls)
    cache_key = f"{product_id}:{product_url}:{product_type}"
    if cache_key in PRODUCT_VAL_CACHE:
        val_res = PRODUCT_VAL_CACHE[cache_key]
    else:
        val_res = product_validator.validate_product_link(
            product_id=product_id,
            product_url=product_url,
            product_type=product_type,
            token=token,
            mock_response=mock_api_response
        )
        if val_res.get("productId"):
            PRODUCT_VAL_CACHE[cache_key] = val_res

    clean_pid = val_res.get("productId") or product_id
    clean_purl = val_res.get("productUrl") or product_url
    clean_ptype = val_res.get("productType") or product_type
    link_attached = val_res.get("isAttached")
    val_status = val_res.get("validationStatus")

    # Flag missing link issue if applicable
    if val_status == "LINK_MISSING":
        if not issue:
            issue = "Product link missing / No deliverable content attached"
        payout_approved = False
    elif val_status == "API_VALIDATION_FAILED":
        # Rule 10: API FAILURE != LINK MISSING
        if not issue:
            issue = "API Validation Error (Manual Review Required)"
        remarks = (remarks + " | Pending manual link verification due to API timeout/error").strip(" |")
        val_status = "MANUAL_REVIEW_REQUIRED"

    # 3. Repeated Issue Detection
    is_repeated = False
    warning_text = ""
    if issue:
        is_repeated, warning_text, _ = issue_tracker.check_issue(creator_id or creator_name, issue)
        issue_tracker.record_issue(
            creator_key=creator_id or creator_name,
            issue_text=issue,
            product_id=clean_pid,
            review_date=review_date,
            payout_status=payout_approved,
            remarks=remarks
        )

    # 4. Generate WhatsApp Message & Payout Decision
    if not payout_approved:
        payout_status_label = "ON HOLD"
        action_req = row.get("actionRequired") or "Attach deliverable content/link to your product page."
        message_text = format_on_hold_message(
            creator_name=creator_name,
            product_name=product_name,
            product_link=clean_purl,
            issue=issue or "Compliance Review Pending",
            remarks=remarks or "Payment is on hold pending resolution.",
            action_required=action_req,
            warning=warning_text
        )
    else:
        payout_status_label = "APPROVED"
        message_text = format_approved_message(
            creator_name=creator_name,
            product_name=product_name,
            product_link=clean_purl,
            remarks=remarks,
            warning=warning_text
        )

    # 5. WhatsApp Notification Dispatch & Duplicate Prevention
    notify_res = notifier.send_notification(
        creator_phone=creator_phone,
        message=message_text,
        creator_id=creator_id,
        product_id=clean_pid,
        review_date=review_date,
        issue=issue,
        mock_send=True
    )

    final_outcome = val_status if val_status not in ("LINK_ATTACHED", "LINK_CONFIRMED") else ("APPROVED" if payout_approved else "ON_HOLD")

    return {
        # Standardized schema (Section 21)
        "creator_id": creator_id,
        "creator_name": creator_name,
        "phone_number": creator_phone,
        "product_id": clean_pid,
        "product_name": product_name,
        "sale_date": sale_date,
        "product_link": clean_purl,
        "payout_status": payout_status_label,
        "issue": issue,
        "remarks": remarks,
        "repeated_issue": "YES" if is_repeated else "NO",
        "validation_status": val_status,
        "final_result": final_outcome,
        # Backward-compatible keys
        "creator": creator_name,
        "creatorPhone": creator_phone,
        "productName": product_name,
        "productId": clean_pid,
        "productType": clean_ptype,
        "productLink": clean_purl,
        "linkAttached": link_attached,
        "validationStatus": val_status,
        "payoutStatus": payout_status_label,
        "payoutApproved": payout_approved,
        "isRepeatedIssue": is_repeated,
        "warning": warning_text,
        "generatedMessage": message_text,
        "whatsappStatus": notify_res,
        "finalOutcome": final_outcome
    }


def filter_yesterday_products(rows, timezone_str="Asia/Kolkata"):
    """
    Filter rows to ONLY include products sold yesterday (T+1 workflow rule).
    """
    dates = agent.get_business_dates(timezone_str=timezone_str)
    yesterday_str = dates["yesterday_date"]
    
    filtered = []
    for r in rows:
        raw_date = str(r.get("saleDate") or r.get("sale_date") or r.get("latestSelfTxnDate") or r.get("createdAt") or "").strip()
        # Extract YYYY-MM-DD or DD-MM-YYYY
        if yesterday_str in raw_date or dates["yesterday_formatted"] in raw_date:
            filtered.append(r)
        elif not raw_date:
            # If no sale date specified, treat as current review batch
            filtered.append(r)
    return filtered


def process_batch(rows, token=None, yesterday_only=True):
    """Process a list/batch of sheet payout rows."""
    if yesterday_only and rows:
        rows = filter_yesterday_products(rows)
    
    issue_tracker = IssueTracker()
    notifier = WhatsAppNotifier()
    results = []
    for r in rows:
        try:
            res = process_payout_row(r, token=token, issue_tracker=issue_tracker, notifier=notifier)
            results.append(res)
        except Exception as e:
            print(f"Error processing row {r}: {e}")
            results.append({
                "creator_id": r.get("creatorId") or r.get("creator_id"),
                "creator_name": r.get("creator") or r.get("username"),
                "product_id": r.get("productId"),
                "payout_status": "ON HOLD",
                "validation_status": "PROCESSING_ERROR",
                "final_result": "PROCESSING_ERROR",
                "error": str(e)
            })
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cosmofeed Payout Automation Orchestrator")
    parser.add_argument("--token", default=os.environ.get("COSMOFEED_TOKEN"))
    default_data_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports", "data.json")
    if not os.path.exists(default_data_file):
        default_data_file = "data.json"
    parser.add_argument("--data-file", default=default_data_file, help="Path to data.json or input sheet JSON")
    parser.add_argument("--limit", type=int, default=10, help="Limit number of rows processed")
    args = parser.parse_args()

    if os.path.exists(args.data_file):
        with open(args.data_file, encoding="utf-8") as f:
            raw_data = json.load(f)
        items = raw_data.get("creators", [])
        if args.limit:
            items = items[:args.limit]
        print(f"Processing batch of {len(items)} items...")
        out_results = process_batch(items, token=args.token)
        print(f"Completed! Sample result:\n{json.dumps(out_results[0], indent=2)}")
