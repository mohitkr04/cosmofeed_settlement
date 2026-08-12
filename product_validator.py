#!/usr/bin/env python3
"""
Product Link Validation Module
==============================
Validates whether a Cosmofeed digital product has deliverable content/links attached
using the production API endpoint:
  IDviewProductDetails?id={PRODUCT_ID}&productType=page

Mandatory Business Rules:
  1. Telegram / Impersonated Product Exception (`vig/{product_id}`):
     Excluded from missing-link validation. Classified as TELEGRAM_VIG_EXCLUDED.
  2. API Failure Handling:
     API failure != Product link missing. Classified as API_VALIDATION_FAILED without false positives.
  3. Dynamic extraction of product IDs and link types (vp, ps, vig, course, page, etc.).
"""

import re
import json
import payout_audit_agent as agent

def extract_product_id(raw_val):
    """Dynamically extract a 24-char hex or UUID product ID from string or URL."""
    if not raw_val:
        return ""
    raw_str = str(raw_val).strip()
    # Match standard 24-char hex MongoDB ID or UUID
    m = re.search(r"([0-9a-fA-F]{24}|[0-9a-fA-F-]{36})", raw_str)
    return m.group(1) if m else raw_str


def parse_page_data_attached(data_obj):
    """
    Traverse pageData or product response structure to determine if content/link is attached.
    Checks unlockedFiles, unlockedLinks, redirectSuccessURL, lc (locked content), products list, modules, etc.
    """
    if not isinstance(data_obj, dict):
        return False, "Empty or invalid pageData response"

    page_data = data_obj.get("pageData") or data_obj

    # 1. Redirect success URL
    redir = page_data.get("redirectSuccessURL") or page_data.get("redirectionLink")
    if isinstance(redir, dict):
        if redir.get("isEnabled") is not False and (redir.get("text") or redir.get("url")):
            return True, "Redirect success URL configured"
    elif isinstance(redir, str) and redir.strip():
        return True, f"Redirect URL present: {redir.strip()}"

    # 2. Unlocked deliverables (unlockedFiles, unlockedLinks, unlockedVideos, etc.)
    for key in ("unlockedFiles", "unlockedLinks", "unlockedVideos", "unlockedImages", "unlockedMessages", "bumpFiles", "bumpUrls", "bumpVideos"):
        items = page_data.get(key)
        if isinstance(items, list) and len(items) > 0:
            return True, f"Attached content found in {key} ({len(items)} item(s))"

    # 3. Product items array (pageData.products)
    prods = page_data.get("products")
    if isinstance(prods, list) and len(prods) > 0:
        for idx, p in enumerate(prods):
            if isinstance(p, dict):
                lc = p.get("lc") or {}
                if isinstance(lc, dict):
                    for media_type in ("file", "video", "link", "image"):
                        m_items = lc.get(media_type)
                        if isinstance(m_items, list) and len(m_items) > 0:
                            return True, f"Locked content {media_type} attached in products[{idx}]"
                course_ids = p.get("courseIds")
                if isinstance(course_ids, list) and len(course_ids) > 0:
                    return True, f"Course IDs attached in products[{idx}]"

    # 4. Root locked content (lc)
    root_lc = page_data.get("lc") or {}
    if isinstance(root_lc, dict):
        for media_type in ("file", "video", "link", "image"):
            m_items = root_lc.get(media_type)
            if isinstance(m_items, list) and len(m_items) > 0:
                return True, f"Locked content {media_type} attached in root lc"

    # 5. Modules, chapters, resources Details
    modules = page_data.get("modules") or page_data.get("chapters") or []
    if isinstance(modules, list) and len(modules) > 0:
        return True, f"Course modules attached ({len(modules)} module(s))"

    res_details = page_data.get("resourcesDetails") or {}
    if isinstance(res_details, dict):
        file_cnt = res_details.get("file", 0)
        video_cnt = res_details.get("video", 0)
        link_cnt = res_details.get("link", 0)
        if file_cnt > 0 or video_cnt > 0 or link_cnt > 0:
            return True, f"Resource details present (file:{file_cnt}, video:{video_cnt}, link:{link_cnt})"

    # 6. Thank you note
    thank_you = page_data.get("thankYouNote") or {}
    if isinstance(thank_you, dict):
        if thank_you.get("isEnabled") and (thank_you.get("note") or thank_you.get("text")):
            return True, "Thank you note configured with content"

    return False, "Payment page exists, but no product/content link is attached"


def validate_product_link(product_id, product_url="", product_type="page", token=None, mock_response=None):
    """
    Validate product link against production IDviewProductDetails API or mock response.
    
    Returns structured result dict:
      - productId
      - productType
      - productUrl
      - isAttached (True/False/None)
      - validationStatus (LINK_ATTACHED, LINK_MISSING, TELEGRAM_VIG_EXCLUDED, API_VALIDATION_FAILED, INVALID_PRODUCT)
      - finalOutcome
      - reason
    """
    clean_pid = extract_product_id(product_id or product_url)
    url_str = str(product_url or "").strip().lower()
    ptype_str = str(product_type or "").strip().lower()

    # Rule 1: vig/{product_id} Telegram exception check
    if "/vig/" in url_str or ptype_str in ("vig", "integratedgroup"):
        return {
            "productId": clean_pid or product_id,
            "productType": "vig",
            "productUrl": product_url or (f"https://superprofile.bio/vig/{clean_pid}" if clean_pid else ""),
            "isAttached": True,
            "validationStatus": "TELEGRAM_VIG_EXCLUDED",
            "finalOutcome": "TELEGRAM_VIG_EXCLUDED",
            "reason": "Excluded from missing-link validation (vig/Telegram product)",
            "isVigExcluded": True
        }

    # Invalid product ID check
    if not clean_pid:
        return {
            "productId": product_id or "",
            "productType": ptype_str or "unknown",
            "productUrl": product_url or "",
            "isAttached": False,
            "validationStatus": "INVALID_PRODUCT",
            "finalOutcome": "INVALID_PRODUCT",
            "reason": "Invalid or missing product ID",
            "isVigExcluded": False
        }

    constructed_url = product_url or f"https://superprofile.bio/vp/{clean_pid}"

    # Handle mock_response (useful for testing or fallback)
    if mock_response is not None:
        if isinstance(mock_response, dict) and "__error__" in mock_response:
            return {
                "productId": clean_pid,
                "productType": ptype_str or "page",
                "productUrl": constructed_url,
                "isAttached": None,
                "validationStatus": "API_VALIDATION_FAILED",
                "finalOutcome": "API_VALIDATION_FAILED",
                "reason": f"API request failed: {mock_response['__error__']}",
                "isVigExcluded": False
            }
        is_att, reason = parse_page_data_attached(mock_response)
        v_status = "LINK_ATTACHED" if is_att else "LINK_MISSING"
        return {
            "productId": clean_pid,
            "productType": ptype_str or "page",
            "productUrl": constructed_url,
            "isAttached": is_att,
            "validationStatus": v_status,
            "finalOutcome": v_status,
            "reason": reason,
            "isVigExcluded": False
        }

    # Query production API endpoint if token available
    api_ptype = "page" if ptype_str in ("vp", "page", "") else ptype_str
    api_res = agent.api_get_product_details(clean_pid, token=token, product_type=api_ptype)

    if not api_res or "__error__" in api_res:
        err_msg = (api_res or {}).get("__error__", "API request failed or timed out")
        return {
            "productId": clean_pid,
            "productType": api_ptype,
            "productUrl": constructed_url,
            "isAttached": None,
            "validationStatus": "API_VALIDATION_FAILED",
            "finalOutcome": "API_VALIDATION_FAILED",
            "reason": f"API request failed: {err_msg}",
            "isVigExcluded": False
        }

    data_payload = api_res.get("data") or {}
    is_att, reason = parse_page_data_attached(data_payload)
    v_status = "LINK_ATTACHED" if is_att else "LINK_MISSING"

    return {
        "productId": clean_pid,
        "productType": api_ptype,
        "productUrl": constructed_url,
        "isAttached": is_att,
        "validationStatus": v_status,
        "finalOutcome": v_status,
        "reason": reason,
        "isVigExcluded": False
    }
