"""
Extraction and resolution of connected Creator IDs.
"""

import re
from typing import Set, Dict, Any, List
from .id_loader import is_valid_creator_id

HEX_24_RE = re.compile(r"^[0-9a-fA-F]{24}$")


def extract_connected_ids_from_kundli(kundli_data: Dict[str, Any], current_creator_id: str) -> Set[str]:
    """
    Extract any connected Creator IDs from the creator's Kundli response or profile data.
    Inspects:
      - Direct connected ID fields: connectedIds, connectedAccounts, connectedCreators, allConnectedIds
      - Related referral accounts: referrerId, referringCreatorId
      - Merged or linked user accounts
    """
    connected: Set[str] = set()
    if not isinstance(kundli_data, dict):
        return connected

    # Check top-level and inner 'data'
    containers = [kundli_data]
    if isinstance(kundli_data.get("data"), dict):
        containers.append(kundli_data["data"])
        if isinstance(kundli_data["data"].get("data"), dict):
            containers.append(kundli_data["data"]["data"])

    for c in containers:
        # 1. Direct connected arrays
        for field_name in ("connectedIds", "allConnectedIds", "connectedAccounts", "connectedCreators", "linkedAccounts", "relatedUsers"):
            val = c.get(field_name)
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, str) and is_valid_creator_id(item):
                        if item.strip() != current_creator_id:
                            connected.add(item.strip())
                    elif isinstance(item, dict):
                        cid = item.get("creatorId") or item.get("userId") or item.get("_id")
                        if cid and is_valid_creator_id(str(cid)):
                            if str(cid).strip() != current_creator_id:
                                connected.add(str(cid).strip())

        # 2. Direct referrer creator ID
        for ref_field in ("referrerId", "referringCreatorId"):
            ref_val = c.get(ref_field)
            if isinstance(ref_val, str) and is_valid_creator_id(ref_val):
                if ref_val.strip() != current_creator_id:
                    connected.add(ref_val.strip())

    return connected
