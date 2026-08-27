"""
Detection heuristics and evidence extractor for SEBI registration badges and text.
"""

import re
from typing import Tuple, Optional, Dict, Any, List
from . import config
from .models import ProductEvidence


def clean_html_tags(raw_html: str) -> str:
    """Strip HTML tags and collapse whitespace."""
    if not raw_html or not isinstance(raw_html, str):
        return ""
    text = re.sub(r"<[^>]+>", " ", raw_html)
    return " ".join(text.split())


def extract_context_snippet(full_text: str, match_start: int, match_end: int, context_chars: int = 60) -> str:
    """Extract a surrounding snippet around a matched position for auditable evidence."""
    start = max(0, match_start - context_chars)
    end = min(len(full_text), match_end + context_chars)
    snippet = full_text[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(full_text):
        snippet = snippet + "..."
    return snippet


def detect_sebi_in_text(raw_text: str, source_label: str = "") -> Tuple[bool, str, str, str]:
    """
    Inspect a text string for SEBI registration indicators.
    Returns:
      (has_sebi: bool, reg_no: str, matched_text: str, evidence_snippet: str)
    """
    if not raw_text or not isinstance(raw_text, str):
        return False, "", "", ""

    clean_text = clean_html_tags(raw_text)

    # 1. Primary check: "Registered with SEBI (<REG_NO>)"
    m_exact = config.SEBI_EXACT_BADGE_PATTERN.search(clean_text)
    if m_exact:
        reg_no = m_exact.group("reg_no")
        matched_str = m_exact.group(0)
        snippet = extract_context_snippet(clean_text, m_exact.start(), m_exact.end())
        return True, reg_no, matched_str, snippet

    # 2. General SEBI registration phrase coupled with registration number
    m_indicator = config.SEBI_TEXT_INDICATOR.search(clean_text)
    if m_indicator:
        # Look for nearby registration number (e.g. INH000019099 or INA...)
        m_reg = config.SEBI_REG_NUMBER_PATTERN.search(clean_text)
        if m_reg:
            reg_no = m_reg.group("reg_no")
            matched_str = f"{m_indicator.group(0)} ({reg_no})"
            snippet = extract_context_snippet(clean_text, m_indicator.start(), max(m_indicator.end(), m_reg.end()))
            return True, reg_no, matched_str, snippet
        else:
            # Found "SEBI registered" phrase but no explicit number
            snippet = extract_context_snippet(clean_text, m_indicator.start(), m_indicator.end())
            return True, "N/A (Number not in text)", m_indicator.group(0), snippet

    # 3. Badge image reference
    if config.SEBI_BADGE_ICON_FILENAME in raw_text:
        # Check if text also references SEBI
        if "sebi" in clean_text.lower():
            m_reg = config.SEBI_REG_NUMBER_PATTERN.search(clean_text)
            reg_no = m_reg.group("reg_no") if m_reg else "N/A"
            return True, reg_no, "SEBI Badge Icon + Text", "Badge checklist-yellow.png found with SEBI reference"

    return False, "", "", ""


def inspect_product_payload(product_id: str,
                            product_data: Dict[str, Any],
                            product_url: str = "",
                            product_type: str = "",
                            default_title: str = "") -> Optional[ProductEvidence]:
    """
    Thoroughly inspect a product API response structure (pageData, description, titles, etc.)
    for SEBI registration evidence.
    """
    if not isinstance(product_data, dict):
        return None

    page_data = product_data.get("pageData") or product_data

    # Collect all searchable text fields with location labels
    search_targets: List[Tuple[str, str]] = []

    # Title
    title = str(page_data.get("title") or page_data.get("productTitle") or default_title or "").strip()
    if title:
        search_targets.append(("Product Title", title))

    # Description (most common location for SEBI details)
    desc = str(page_data.get("description") or "").strip()
    if desc:
        search_targets.append(("Product Description", desc))

    # Thank you note
    thank_you = page_data.get("thankYouNote") or {}
    if isinstance(thank_you, dict):
        ty_text = str(thank_you.get("note") or thank_you.get("text") or "").strip()
        if ty_text:
            search_targets.append(("Thank You Note", ty_text))

    # Modules / Chapters titles or descriptions
    modules = page_data.get("modules") or page_data.get("chapters") or []
    if isinstance(modules, list):
        for idx, m in enumerate(modules):
            if isinstance(m, dict):
                m_title = m.get("title") or ""
                m_desc = m.get("description") or ""
                if m_title:
                    search_targets.append((f"Module[{idx}] Title", str(m_title)))
                if m_desc:
                    search_targets.append((f"Module[{idx}] Description", str(m_desc)))

    # Locked content notes / products array
    sub_prods = page_data.get("products") or []
    if isinstance(sub_prods, list):
        for idx, sp in enumerate(sub_prods):
            if isinstance(sp, dict):
                sp_title = sp.get("title") or ""
                if sp_title:
                    search_targets.append((f"SubProduct[{idx}] Title", str(sp_title)))

    # Inspect each target
    for field_label, text_content in search_targets:
        has_sebi, reg_no, matched_text, snippet = detect_sebi_in_text(text_content, source_label=field_label)
        if has_sebi:
            evidence = ProductEvidence(
                product_id=product_id,
                product_name=title or default_title or "Untitled Product",
                product_type=product_type or page_data.get("productType") or "page",
                product_link=product_url or f"{config.SUPERPROFILE_BASE_URL}/vp/{product_id}",
                sebi_registration_text=matched_text,
                sebi_registration_number=reg_no or "N/A",
                evidence_source=f"Product Page ({field_label}): {snippet}",
                has_sebi=True
            )
            return evidence

    return None
