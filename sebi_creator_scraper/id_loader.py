"""
Harvests and normalizes existing Creator IDs from project reports, audit JSON files, and settlement reviews.
"""

import os
import re
import json
import glob
from typing import Dict, Set, Tuple, List, Optional, Any
from . import config

HEX_24_RE = re.compile(r"^[0-9a-fA-F]{24}$")


def is_valid_creator_id(cid: str) -> bool:
    """Validate whether string is a valid MongoDB 24-char hex ID."""
    if not cid or not isinstance(cid, str):
        return False
    return bool(HEX_24_RE.match(cid.strip()))


def extract_ids_from_object(obj: Any, found_map: Dict[str, Set[str]], source_tag: str) -> None:
    """Recursively traverse a JSON structure to find valid Creator IDs."""
    if isinstance(obj, dict):
        # Direct creator ID fields
        for key in ("creatorId", "userId", "_id"):
            val = obj.get(key)
            if isinstance(val, str) and is_valid_creator_id(val):
                # Distinguish user/creator IDs from random transaction/settlement IDs
                if key in ("creatorId", "userId") or "username" in obj or "DisplayName" in obj:
                    clean_id = val.strip()
                    if clean_id not in found_map:
                        found_map[clean_id] = set()
                    found_map[clean_id].add(source_tag)

        for v in obj.values():
            if isinstance(v, (dict, list)):
                extract_ids_from_object(v, found_map, source_tag)
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                extract_ids_from_object(item, found_map, source_tag)


def load_ids_from_reports(reports_dir: Optional[str] = None) -> Dict[str, Set[str]]:
    """
    Extract all unique Creator IDs across existing reports and audit JSON files.
    Returns dict of {creator_id: {discovery_sources}}.
    """
    target_dir = reports_dir or config.REPORTS_DIR
    found: Dict[str, Set[str]] = {}

    if not os.path.exists(target_dir):
        return found

    json_files = glob.glob(os.path.join(target_dir, "*.json"))
    for file_path in json_files:
        filename = os.path.basename(file_path)
        # Identify source classification
        if filename.startswith("audit_"):
            source_tag = f"Audit ({filename})"
        elif filename == "data.json":
            source_tag = "Existing JSON (data.json)"
        elif filename.startswith("self_txn_"):
            source_tag = f"Self Txn ({filename})"
        else:
            source_tag = f"Existing JSON ({filename})"

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                extract_ids_from_object(data, found, source_tag)
        except Exception:
            continue

    return found


def load_ids_from_settlements(api_client, max_pages: int = 5) -> Dict[str, Set[str]]:
    """
    Fetch Creator IDs directly from live pending settlements page.
    """
    found: Dict[str, Set[str]] = {}
    if not api_client:
        return found

    try:
        first_page = api_client.get_settlements_page(page=1)
        if not first_page or "__error__" in first_page:
            return found

        data = first_page.get("data", {})
        total_pages = min(data.get("totalPages", 1), max_pages)
        rows = data.get("settelements") or data.get("settlements") or []

        source_tag = "Settlement Review"
        for r in rows:
            cid = r.get("creatorId") or r.get("userId")
            if cid and is_valid_creator_id(cid):
                clean_id = cid.strip()
                if clean_id not in found:
                    found[clean_id] = set()
                found[clean_id].add(source_tag)

        # Subsequent pages
        for p in range(2, total_pages + 1):
            page_data = api_client.get_settlements_page(page=p)
            prows = (page_data.get("data") or {}).get("settelements") or (page_data.get("data") or {}).get("settlements") or []
            for r in prows:
                cid = r.get("creatorId") or r.get("userId")
                if cid and is_valid_creator_id(cid):
                    clean_id = cid.strip()
                    if clean_id not in found:
                        found[clean_id] = set()
                    found[clean_id].add(source_tag)
    except Exception:
        pass

    return found


def load_all_initial_creator_ids(api_client=None, include_settlement_review: bool = False) -> Dict[str, Set[str]]:
    """
    Combine all offline reports and audit data (and optionally live settlements)
    into a unified, deduplicated mapping of {creator_id: {sources}}.
    """
    all_creators = load_ids_from_reports()

    if include_settlement_review and api_client:
        settlement_creators = load_ids_from_settlements(api_client)
        for cid, srcs in settlement_creators.items():
            if cid not in all_creators:
                all_creators[cid] = set()
            all_creators[cid].update(srcs)

    return all_creators
