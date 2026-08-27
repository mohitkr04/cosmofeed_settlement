"""
Product traversal and inspection module for all product categories, including VIG/Telegram.
"""

from typing import Dict, Any, List, Optional, Tuple
from .api_client import CosmofeedApiClient
from .models import ProductEvidence
from .sebi_detector import detect_sebi_in_text, inspect_product_payload
from . import config

# Global product-level cache to eliminate redundant API calls across creators sharing products
PRODUCT_INSPECTION_CACHE: Dict[str, Optional[ProductEvidence]] = {}


def extract_kundli_array(resp: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    """Extract array from nested Kundli response structures."""
    if not isinstance(resp, dict):
        return []
    data_val = resp.get("data")
    if isinstance(data_val, list):
        return [x for x in data_val if isinstance(x, dict)]
    if isinstance(data_val, dict):
        inner_val = data_val.get("data")
        if isinstance(inner_val, list):
            return [x for x in inner_val if isinstance(x, dict)]
        if isinstance(inner_val, dict):
            res = inner_val.get(key)
            if isinstance(res, list):
                return [x for x in res if isinstance(x, dict)]
        res = data_val.get(key)
        if isinstance(res, list):
            return [x for x in res if isinstance(x, dict)]
    return []


def fetch_creator_products(creator_id: str, api_client: CosmofeedApiClient) -> List[Dict[str, Any]]:
    """Retrieve creator's sold products list via getCreatorKundli."""
    res = api_client.get_creator_kundli(creator_id, requested_action="lastHundredSoldProducts")
    if not res or "__error__" in res:
        return []
    return extract_kundli_array(res, "lastHundredSoldProducts")


def inspect_product(raw_product: Dict[str, Any], api_client: CosmofeedApiClient) -> Optional[ProductEvidence]:
    """
    Inspect a single product (normal page, VIG / Telegram, course, etc.) for SEBI registration.
    Uses product-level caching to avoid duplicate requests.
    """
    pid = str(raw_product.get("_id") or raw_product.get("productId") or "").strip()
    raw_title = str(raw_product.get("productTtile") or raw_product.get("productTitle") or raw_product.get("title") or "").strip()
    raw_url = str(raw_product.get("productLink") or raw_product.get("url") or "").strip()
    raw_type = str(raw_product.get("productType") or "").strip()

    # Determine normalized type (do NOT exclude VIG products!)
    norm_type = raw_type
    if "/vig/" in raw_url or raw_type in ("integratedGroup", "vig"):
        norm_type = "vig"
    elif "/course/" in raw_url or raw_type == "course":
        norm_type = "course"
    elif not norm_type:
        norm_type = "page"

    product_url = raw_url
    if not product_url and pid:
        if norm_type == "vig":
            product_url = f"{config.SUPERPROFILE_BASE_URL}/vig/{pid}"
        elif norm_type == "course":
            product_url = f"{config.SUPERPROFILE_BASE_URL}/course/{pid}"
        else:
            product_url = f"{config.SUPERPROFILE_BASE_URL}/vp/{pid}"

    cache_key = pid or product_url
    if cache_key and cache_key in PRODUCT_INSPECTION_CACHE:
        return PRODUCT_INSPECTION_CACHE[cache_key]

    # Fast path: check product title directly
    has_sebi, reg_no, matched_text, snippet = detect_sebi_in_text(raw_title, source_label="Product Title")
    if has_sebi:
        evidence = ProductEvidence(
            product_id=pid,
            product_name=raw_title,
            product_type=norm_type,
            product_link=product_url,
            sebi_registration_text=matched_text,
            sebi_registration_number=reg_no or "N/A",
            evidence_source=f"Product Title: {snippet}",
            has_sebi=True
        )
        if cache_key:
            PRODUCT_INSPECTION_CACHE[cache_key] = evidence
        return evidence

    # Query detailed product payload via IDviewProductDetails
    if pid and api_client:
        api_ptype = "page" if norm_type in ("vp", "page", "") else norm_type
        prod_details = api_client.get_product_details(pid, product_type=api_ptype)
        if prod_details and "__error__" not in prod_details:
            evidence = inspect_product_payload(
                product_id=pid,
                product_data=prod_details.get("data") or prod_details,
                product_url=product_url,
                product_type=norm_type,
                default_title=raw_title
            )
            if evidence:
                if cache_key:
                    PRODUCT_INSPECTION_CACHE[cache_key] = evidence
                return evidence

    # No SEBI evidence found for this product
    if cache_key:
        PRODUCT_INSPECTION_CACHE[cache_key] = None
    return None


def inspect_all_creator_products(creator_id: str, api_client: CosmofeedApiClient) -> Tuple[bool, str, str, List[ProductEvidence], int]:
    """
    Fetch and inspect all applicable products for a creator.
    Includes normal products, courses, and VIG/Telegram products.
    Returns:
      (is_sebi, registration_number, combined_evidence, evidence_list, total_checked)
    """
    products = fetch_creator_products(creator_id, api_client)
    total_checked = len(products)
    sebi_evidence_list: List[ProductEvidence] = []

    for p in products:
        ev = inspect_product(p, api_client)
        if ev and ev.has_sebi:
            sebi_evidence_list.append(ev)
            # Early exit: SEBI registration is confirmed for this creator!
            break

    if sebi_evidence_list:
        # Pick the most specific registration number found
        reg_numbers = [e.sebi_registration_number for e in sebi_evidence_list if e.sebi_registration_number and e.sebi_registration_number != "N/A"]
        best_reg_no = reg_numbers[0] if reg_numbers else "N/A"

        # Combine evidence summaries
        ev_summaries = [f"[{e.product_type.upper()}] {e.product_name}: {e.sebi_registration_text} (Source: {e.evidence_source})" for e in sebi_evidence_list]
        combined_evidence = " | ".join(ev_summaries)

        return True, best_reg_no, combined_evidence, sebi_evidence_list, total_checked

    return False, "N/A", "N/A", [], total_checked
