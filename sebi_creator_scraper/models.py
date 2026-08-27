"""
Data models and representations for SEBI creator discovery.
"""

import datetime
from dataclasses import dataclass, field
from typing import List, Set, Optional, Dict, Any


@dataclass
class ProductEvidence:
    """Represents auditable evidence of SEBI registration found on a product."""
    product_id: str = ""
    product_name: str = ""
    product_type: str = ""
    product_link: str = ""
    sebi_registration_text: str = ""
    sebi_registration_number: str = ""
    evidence_source: str = ""
    has_sebi: bool = False
    checked_at: str = field(default_factory=lambda: datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "productId": self.product_id or "N/A",
            "productName": self.product_name or "N/A",
            "productType": self.product_type or "N/A",
            "productLink": self.product_link or "N/A",
            "sebiRegistrationText": self.sebi_registration_text or "N/A",
            "sebiRegistrationNumber": self.sebi_registration_number or "N/A",
            "evidenceSource": self.evidence_source or "N/A",
            "hasSebi": self.has_sebi,
            "checkedAt": self.checked_at
        }


@dataclass
class CreatorProfile:
    """Represents a unique creator profile with normalized details and SEBI status."""
    creator_id: str
    username: str = "N/A"
    email: str = "N/A"
    onboarded_by: str = "N/A"
    onboarding_vertical: str = "N/A"
    display_name: str = "N/A"
    phone: str = "N/A"
    category: str = "N/A"
    sebi_registered: str = "NO"  # "YES", "NO", "MANUAL_REVIEW"
    sebi_registration_number: str = "N/A"
    sebi_evidence: str = "N/A"
    discovery_sources: Set[str] = field(default_factory=set)
    connected_creator_ids: Set[str] = field(default_factory=set)
    products_checked: int = 0
    product_evidence: List[ProductEvidence] = field(default_factory=list)
    status: str = "PENDING"  # PENDING, PROCESSING, COMPLETED, SEBI_REGISTERED, NOT_SEBI_REGISTERED, MANUAL_REVIEW, ERROR
    error_message: str = ""
    last_checked: str = field(default_factory=lambda: datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def merge(self, other: "CreatorProfile") -> None:
        """Merge metadata and discovery sources from another record into this unique profile."""
        if not self.creator_id:
            self.creator_id = other.creator_id

        # Update N/A fields with valid values if available
        if (not self.username or self.username == "N/A") and other.username and other.username != "N/A":
            self.username = other.username
        if (not self.email or self.email == "N/A") and other.email and other.email != "N/A":
            self.email = other.email
        if (not self.onboarded_by or self.onboarded_by == "N/A") and other.onboarded_by and other.onboarded_by != "N/A":
            self.onboarded_by = other.onboarded_by
        if (not self.onboarding_vertical or self.onboarding_vertical == "N/A") and other.onboarding_vertical and other.onboarding_vertical != "N/A":
            self.onboarding_vertical = other.onboarding_vertical
        if (not self.display_name or self.display_name == "N/A") and other.display_name and other.display_name != "N/A":
            self.display_name = other.display_name
        if (not self.phone or self.phone == "N/A") and other.phone and other.phone != "N/A":
            self.phone = other.phone
        if (not self.category or self.category == "N/A") and other.category and other.category != "N/A":
            self.category = other.category

        # Combine discovery sources
        self.discovery_sources.update(other.discovery_sources)
        self.connected_creator_ids.update(other.connected_creator_ids)

        # Merge SEBI status: YES takes priority over NO
        if other.sebi_registered == "YES":
            self.sebi_registered = "YES"
            if other.sebi_registration_number and other.sebi_registration_number != "N/A":
                self.sebi_registration_number = other.sebi_registration_number
            if other.sebi_evidence and other.sebi_evidence != "N/A":
                if self.sebi_evidence and self.sebi_evidence != "N/A" and other.sebi_evidence not in self.sebi_evidence:
                    self.sebi_evidence = f"{self.sebi_evidence} | {other.sebi_evidence}"
                else:
                    self.sebi_evidence = other.sebi_evidence
            self.status = "SEBI_REGISTERED"

        # Combine product evidence
        existing_pids = {p.product_id for p in self.product_evidence if p.product_id}
        for pe in other.product_evidence:
            if pe.product_id and pe.product_id not in existing_pids:
                self.product_evidence.append(pe)
                existing_pids.add(pe.product_id)

        self.products_checked = max(self.products_checked, other.products_checked, len(self.product_evidence))
        if other.error_message and not self.error_message:
            self.error_message = other.error_message

    def to_dict(self) -> Dict[str, Any]:
        return {
            "creatorId": self.creator_id,
            "username": self.username,
            "email": self.email,
            "onboardedBy": self.onboarded_by,
            "onboardingVertical": self.onboarding_vertical,
            "displayName": self.display_name,
            "phone": self.phone,
            "category": self.category,
            "sebiRegistered": self.sebi_registered,
            "sebiRegistrationNumber": self.sebi_registration_number,
            "sebiEvidence": self.sebi_evidence,
            "discoverySource": ", ".join(sorted(self.discovery_sources)) if self.discovery_sources else "N/A",
            "connectedCreatorIds": ", ".join(sorted(self.connected_creator_ids)) if self.connected_creator_ids else "N/A",
            "productsChecked": self.products_checked,
            "productEvidence": [p.to_dict() for p in self.product_evidence],
            "status": self.status,
            "errorMessage": self.error_message,
            "lastChecked": self.last_checked
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CreatorProfile":
        cp = cls(
            creator_id=d.get("creatorId", ""),
            username=d.get("username", "N/A"),
            email=d.get("email", "N/A"),
            onboarded_by=d.get("onboardedBy", "N/A"),
            onboarding_vertical=d.get("onboardingVertical", "N/A"),
            display_name=d.get("displayName", "N/A"),
            phone=d.get("phone", "N/A"),
            category=d.get("category", "N/A"),
            sebi_registered=d.get("sebiRegistered", "NO"),
            sebi_registration_number=d.get("sebiRegistrationNumber", "N/A"),
            sebi_evidence=d.get("sebiEvidence", "N/A"),
            products_checked=d.get("productsChecked", 0),
            status=d.get("status", "COMPLETED"),
            error_message=d.get("errorMessage", ""),
            last_checked=d.get("lastChecked", "")
        )
        # Parse discovery sources
        srcs = d.get("discoverySource", "")
        if srcs and srcs != "N/A":
            cp.discovery_sources = {s.strip() for s in srcs.split(",") if s.strip()}
        # Parse connected IDs
        cids = d.get("connectedCreatorIds", "")
        if cids and cids != "N/A":
            cp.connected_creator_ids = {c.strip() for c in cids.split(",") if c.strip()}
        # Parse product evidence
        for pe_dict in d.get("productEvidence", []):
            cp.product_evidence.append(ProductEvidence(
                product_id=pe_dict.get("productId", ""),
                product_name=pe_dict.get("productName", ""),
                product_type=pe_dict.get("productType", ""),
                product_link=pe_dict.get("productLink", ""),
                sebi_registration_text=pe_dict.get("sebiRegistrationText", ""),
                sebi_registration_number=pe_dict.get("sebiRegistrationNumber", ""),
                evidence_source=pe_dict.get("evidenceSource", ""),
                has_sebi=pe_dict.get("hasSebi", False),
                checked_at=pe_dict.get("checkedAt", "")
            ))
        return cp
