"""
Recursive queue and state manager with deduplication, source merging, and error isolation.
"""

import collections
import datetime
from typing import Dict, Set, List, Optional, Tuple, Any

from .models import CreatorProfile, ProductEvidence
from .api_client import CosmofeedApiClient
from .creator_info import fetch_creator_profile
from .product_checker import inspect_all_creator_products


class QueueManager:
    """
    Coordinates the processing of creator IDs, deduplication,
    recursive discovery of connected IDs, and safe error isolation.
    """

    def __init__(self):
        self.creators: Dict[str, CreatorProfile] = {}
        self.visited: Set[str] = set()
        self.pending_queue: collections.deque[str] = collections.deque()
        self.discovered_ids: Set[str] = set()

        self.stats = {
            "initial_ids_count": 0,
            "unique_discovered": 0,
            "processed": 0,
            "sebi_registered": 0,
            "not_sebi_registered": 0,
            "manual_review": 0,
            "errors": 0,
            "duplicates_merged": 0
        }

    def add_initial_creators(self, id_source_map: Dict[str, Set[str]]) -> None:
        """Enqueue initial set of creators harvested from existing reports and audits."""
        self.stats["initial_ids_count"] = len(id_source_map)

        for cid, sources in id_source_map.items():
            clean_id = cid.strip()
            if clean_id not in self.creators:
                prof = CreatorProfile(creator_id=clean_id, status="PENDING")
                prof.discovery_sources.update(sources)
                self.creators[clean_id] = prof
                self.discovered_ids.add(clean_id)
                self.pending_queue.append(clean_id)
            else:
                self.creators[clean_id].discovery_sources.update(sources)
                self.stats["duplicates_merged"] += 1

        self.stats["unique_discovered"] = len(self.discovered_ids)

    def enqueue_connected_id(self, parent_id: str, new_id: str) -> bool:
        """
        Add a newly discovered connected Creator ID to queue and register discovery source.
        Returns True if new ID was enqueued, False if already known.
        """
        clean_id = new_id.strip()
        source_label = f"Connected Creator ID ({parent_id})"

        if clean_id in self.creators:
            # Already known: merge discovery source and track connection
            self.creators[clean_id].discovery_sources.add(source_label)
            self.stats["duplicates_merged"] += 1
            return False

        # New ID discovered!
        prof = CreatorProfile(creator_id=clean_id, status="PENDING")
        prof.discovery_sources.add(source_label)
        self.creators[clean_id] = prof
        self.discovered_ids.add(clean_id)
        self.pending_queue.append(clean_id)
        self.stats["unique_discovered"] = len(self.discovered_ids)
        return True

    def has_pending(self) -> bool:
        return len(self.pending_queue) > 0

    def next_creator_id(self) -> Optional[str]:
        while self.pending_queue:
            cid = self.pending_queue.popleft()
            if cid not in self.visited:
                return cid
        return None

    def process_one(self, creator_id: str, api_client: CosmofeedApiClient) -> CreatorProfile:
        """
        Full isolated lifecycle for one Creator ID:
          1. Mark visited
          2. Fetch Creator Info via getCreatorKundli
          3. Extract Connected IDs and enqueue them
          4. Inspect Products (normal, courses, VIG / Telegram)
          5. Detect SEBI registration and preserve evidence
          6. Update status and statistics
        """
        self.visited.add(creator_id)
        existing_profile = self.creators.get(creator_id) or CreatorProfile(creator_id=creator_id)
        existing_sources = set(existing_profile.discovery_sources)

        # 1. Fetch Creator Info
        try:
            fetched_profile = fetch_creator_profile(creator_id, api_client)
        except Exception as e:
            existing_profile.status = "ERROR"
            existing_profile.error_message = f"Unhandled Profile Error: {str(e)}"
            self.stats["processed"] += 1
            self.stats["errors"] += 1
            self.creators[creator_id] = existing_profile
            return existing_profile

        # Preserve previously accumulated discovery sources
        fetched_profile.discovery_sources.update(existing_sources)

        if fetched_profile.status == "ERROR":
            self.stats["processed"] += 1
            self.stats["errors"] += 1
            self.creators[creator_id] = fetched_profile
            return fetched_profile

        # 2. Enqueue connected IDs
        for conn_id in fetched_profile.connected_creator_ids:
            self.enqueue_connected_id(parent_id=creator_id, new_id=conn_id)

        # 3. Product Inspection (including VIG/Telegram)
        try:
            is_sebi, reg_no, combined_ev, evidence_list, total_prods = inspect_all_creator_products(creator_id, api_client)
            fetched_profile.products_checked = total_prods
            fetched_profile.product_evidence = evidence_list

            if is_sebi:
                fetched_profile.sebi_registered = "YES"
                fetched_profile.sebi_registration_number = reg_no or "N/A"
                fetched_profile.sebi_evidence = combined_ev or "SEBI registration confirmed on product page"
                fetched_profile.status = "SEBI_REGISTERED"
                self.stats["sebi_registered"] += 1
            else:
                fetched_profile.sebi_registered = "NO"
                fetched_profile.sebi_registration_number = "N/A"
                fetched_profile.sebi_evidence = "N/A"
                fetched_profile.status = "NOT_SEBI_REGISTERED"
                self.stats["not_sebi_registered"] += 1

        except Exception as e:
            fetched_profile.status = "ERROR"
            fetched_profile.error_message = f"Product Inspection Error: {str(e)}"
            self.stats["errors"] += 1

        fetched_profile.last_checked = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.stats["processed"] += 1
        self.creators[creator_id] = fetched_profile
        return fetched_profile
