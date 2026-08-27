"""
CLI Orchestrator and runner for SEBI Registered Creator Discovery workflow.
"""

import os
import sys
import argparse
import logging
from typing import Optional

from . import config
from .models import CreatorProfile
from .api_client import CosmofeedApiClient
from .id_loader import load_all_initial_creator_ids
from .queue_manager import QueueManager
from .checkpoint import CheckpointManager
from .exporter import export_to_excel, export_to_csv

# Setup logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("sebi_scraper")


def validate_before_export(creators: list[CreatorProfile]) -> bool:
    """Validate data integrity before exporting."""
    logger.info("Running pre-export data validation...")
    seen_ids = set()
    for c in creators:
        if not c.creator_id:
            logger.error("Pre-export check failed: Record with empty Creator ID found.")
            return False
        if c.creator_id in seen_ids:
            logger.error(f"Pre-export check failed: Duplicate Creator ID detected: {c.creator_id}")
            return False
        seen_ids.add(c.creator_id)

    logger.info(f"Pre-export validation passed: {len(seen_ids)} unique creators verified.")
    return True


def run_sebi_discovery(limit: Optional[int] = None,
                       resume: bool = False,
                       include_settlements: bool = False,
                       output_excel: Optional[str] = None,
                       output_csv: Optional[str] = None) -> QueueManager:
    """Run full automated SEBI discovery workflow."""
    logger.info("=" * 60)
    logger.info("Starting SEBI Registered Creator Discovery Workflow")
    logger.info("=" * 60)

    api_client = CosmofeedApiClient()
    queue = QueueManager()
    checkpoint_mgr = CheckpointManager()

    # Resumption handling
    if resume and checkpoint_mgr.exists():
        logger.info(f"Resuming from checkpoint file: {checkpoint_mgr.checkpoint_path}")
        saved_state = checkpoint_mgr.load()
        saved_creators = saved_state.get("creators", {})
        for cid, c_dict in saved_creators.items():
            prof = CreatorProfile.from_dict(c_dict)
            queue.creators[cid] = prof
            queue.discovered_ids.add(cid)

        queue.visited = set(saved_state.get("visitedIds", []))
        queue.pending_queue.extend(saved_state.get("pendingQueue", []))
        queue.stats = saved_state.get("stats", queue.stats)
        logger.info(f"Loaded {len(queue.visited)} already processed creators, {len(queue.pending_queue)} pending.")
    else:
        logger.info("Harvesting initial Creator IDs from existing reports and audits...")
        initial_map = load_all_initial_creator_ids(
            api_client=api_client if include_settlements else None,
            include_settlement_review=include_settlements
        )
        logger.info(f"Loaded {len(initial_map):,} initial unique Creator IDs from reports/audits.")
        queue.add_initial_creators(initial_map)

    processed_count = 0
    save_counter = 0

    while queue.has_pending():
        if limit is not None and processed_count >= limit:
            logger.info(f"Reached user execution limit of {limit} creators.")
            break

        cid = queue.next_creator_id()
        if not cid:
            break

        logger.info(f"[{processed_count + 1}] Processing Creator ID: {cid}")
        profile = queue.process_one(cid, api_client)
        processed_count += 1
        save_counter += 1

        if profile.sebi_registered == "YES":
            logger.info(f"  -> [SEBI REGISTERED] {cid} ({profile.username}) | RegNo: {profile.sebi_registration_number}")
        elif profile.status == "ERROR":
            logger.warning(f"  -> [ERROR] {cid}: {profile.error_message}")
        else:
            logger.info(f"  -> [NOT SEBI] {cid} ({profile.username}) | Products checked: {profile.products_checked}")

        # Periodic checkpoint
        if save_counter >= config.CHECKPOINT_INTERVAL:
            checkpoint_mgr.save(
                creators_map=queue.creators,
                visited_ids=queue.visited,
                pending_queue=list(queue.pending_queue),
                stats=queue.stats
            )
            save_counter = 0

    # Final checkpoint save
    checkpoint_mgr.save(
        creators_map=queue.creators,
        visited_ids=queue.visited,
        pending_queue=list(queue.pending_queue),
        stats=queue.stats
    )

    # Collect all processed creators for export
    all_creators = list(queue.creators.values())
    validate_before_export(all_creators)

    # Export to Excel and CSV
    excel_path = export_to_excel(all_creators, output_path=output_excel)
    csv_path = export_to_csv(all_creators, output_path=output_csv)

    # Print Final Summary
    print("\n" + "=" * 60)
    print("FINAL SUMMARY: SEBI CREATOR DISCOVERY")
    print("=" * 60)
    print(f"Total Initial Creator IDs     : {queue.stats['initial_ids_count']:,}")
    print(f"Unique Creator IDs Discovered : {queue.stats['unique_discovered']:,}")
    print(f"Creators Processed            : {queue.stats['processed']:,}")
    print(f"SEBI Registered Creators      : {queue.stats['sebi_registered']:,}")
    print(f"Not SEBI Registered           : {queue.stats['not_sebi_registered']:,}")
    print(f"Errors Encountered            : {queue.stats['errors']:,}")
    print(f"Duplicate IDs Merged          : {queue.stats['duplicates_merged']:,}")
    print("\nGenerated Artifacts:")
    print(f"  Excel (.xlsx) : {excel_path}")
    print(f"  CSV   (.csv)  : {csv_path}")
    print(f"  Checkpoint    : {checkpoint_mgr.checkpoint_path}")
    print("=" * 60 + "\n")

    return queue


def main():
    parser = argparse.ArgumentParser(description="SEBI Registered Creator Discovery Scraper")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of creators to process (for testing)")
    parser.add_argument("--resume", action="store_true", help="Resume from last checkpoint if available")
    parser.add_argument("--include-settlements", action="store_true", help="Fetch live settlements from dashboard")
    parser.add_argument("--output-excel", type=str, default=None, help="Path for generated Excel file")
    parser.add_argument("--output-csv", type=str, default=None, help="Path for generated CSV file")

    args = parser.parse_args()
    run_sebi_discovery(
        limit=args.limit,
        resume=args.resume,
        include_settlements=args.include_settlements,
        output_excel=args.output_excel,
        output_csv=args.output_csv
    )


if __name__ == "__main__":
    main()
