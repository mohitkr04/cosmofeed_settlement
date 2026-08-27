"""
Retrieval and normalization of creator profile details from Cosmofeed internal API.
"""

from typing import Dict, Any, Tuple
from .models import CreatorProfile
from .api_client import CosmofeedApiClient
from .connected_ids import extract_connected_ids_from_kundli


def fetch_creator_profile(creator_id: str, api_client: CosmofeedApiClient) -> CreatorProfile:
    """
    Fetch and normalize creator profile details via getCreatorKundli.
    Preserves actual values, defaults missing fields to 'N/A', and extracts connected IDs.
    """
    profile = CreatorProfile(creator_id=creator_id)

    if not creator_id:
        profile.status = "ERROR"
        profile.error_message = "Empty or invalid Creator ID"
        return profile

    res = api_client.get_creator_kundli(creator_id)
    if not res or "__error__" in res:
        err = (res or {}).get("__error__", "API request failed")
        profile.status = "ERROR"
        profile.error_message = f"Kundli API Error: {err}"
        return profile

    data_wrap = res.get("data", {})
    # Kundli payload can be inside data.data or data directly
    inner = data_wrap.get("data", {}) if isinstance(data_wrap.get("data"), dict) else data_wrap

    if not isinstance(inner, dict):
        profile.status = "ERROR"
        profile.error_message = "Malformed Kundli response payload"
        return profile

    # Extract core attributes
    profile.username = str(inner.get("Username") or inner.get("username") or "").strip() or "N/A"
    profile.email = str(inner.get("Email") or inner.get("email") or "").strip() or "N/A"
    profile.onboarded_by = str(inner.get("onboardedBy") or inner.get("onboarded_by") or "").strip() or "N/A"
    profile.onboarding_vertical = str(inner.get("vertical") or inner.get("onboardingVertical") or "").strip() or "N/A"
    profile.display_name = str(inner.get("DisplayName") or inner.get("displayName") or "").strip() or "N/A"
    profile.phone = str(inner.get("PhoneNumber") or inner.get("phone") or "").strip() or "N/A"
    profile.category = str(inner.get("category") or "").strip() or "N/A"

    # Extract connected Creator IDs
    connected = extract_connected_ids_from_kundli(res, current_creator_id=creator_id)
    profile.connected_creator_ids = connected

    profile.status = "PROCESSING"
    return profile
