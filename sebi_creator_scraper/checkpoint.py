"""
Atomic checkpointing and resumption state manager for SEBI creator discovery.
"""

import os
import json
import datetime
from typing import Dict, Set, List, Any, Optional
from . import config
from .models import CreatorProfile


class CheckpointManager:
    """Manages persistent checkpointing to disk so scraping runs can resume without data loss."""

    def __init__(self, checkpoint_path: Optional[str] = None):
        self.checkpoint_path = checkpoint_path or config.CHECKPOINT_FILE
        os.makedirs(os.path.dirname(os.path.abspath(self.checkpoint_path)), exist_ok=True)

    def exists(self) -> bool:
        return os.path.exists(self.checkpoint_path) and os.path.getsize(self.checkpoint_path) > 10

    def load(self) -> Dict[str, Any]:
        """Load state from checkpoint file."""
        if not self.exists():
            return {}
        try:
            with open(self.checkpoint_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def save(self,
             creators_map: Dict[str, CreatorProfile],
             visited_ids: Set[str],
             pending_queue: List[str],
             stats: Dict[str, Any]) -> bool:
        """Atomically persist current state to disk."""
        tmp_path = self.checkpoint_path + ".tmp"
        try:
            state = {
                "savedAt": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "stats": stats,
                "visitedIds": list(visited_ids),
                "pendingQueue": pending_queue,
                "creators": {cid: p.to_dict() for cid, p in creators_map.items()}
            }
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)

            # Atomic replace
            if os.path.exists(self.checkpoint_path):
                os.replace(tmp_path, self.checkpoint_path)
            else:
                os.rename(tmp_path, self.checkpoint_path)
            return True
        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            return False

    def clear(self) -> None:
        """Clear existing checkpoint file."""
        if os.path.exists(self.checkpoint_path):
            try:
                os.remove(self.checkpoint_path)
            except Exception:
                pass
