"""
execution/ -- Task execution engine with monitoring, rollback, and checkpoints.
"""

import logging
import os
import time
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("vyren.execution")

CHECKPOINT_DIR = Path(os.path.expanduser("~/.vyren/checkpoints"))


@dataclass
class Checkpoint:
    id: str
    name: str
    description: str
    files: dict = field(default_factory=dict)  # path -> content snapshot
    created: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CheckpointManager:
    """Create and restore checkpoints for safe file operations."""

    def __init__(self):
        CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

    def create(self, name: str, description: str, paths: list[str]) -> str:
        """Create a checkpoint of the given files."""
        cp_id = f"cp_{int(time.time())}"
        cp = Checkpoint(id=cp_id, name=name, description=description)

        for path in paths:
            resolved = Path(path)
            if resolved.is_file():
                try:
                    with open(resolved, "r", encoding="utf-8", errors="replace") as f:
                        cp.files[path] = f.read()
                except Exception:
                    pass

        # Save checkpoint
        cp_path = CHECKPOINT_DIR / f"{cp_id}.json"
        data = {
            "id": cp.id, "name": cp.name, "description": cp.description,
            "created": cp.created, "files": cp.files,
        }
        with open(cp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"Checkpoint created: {name} ({len(cp.files)} files)")
        return cp_id

    def restore(self, cp_id: str) -> bool:
        """Restore files from a checkpoint."""
        cp_path = CHECKPOINT_DIR / f"{cp_id}.json"
        if not cp_path.exists():
            return False

        try:
            with open(cp_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            restored = 0
            for path, content in data.get("files", {}).items():
                resolved = Path(path)
                resolved.parent.mkdir(parents=True, exist_ok=True)
                with open(resolved, "w", encoding="utf-8") as f:
                    f.write(content)
                restored += 1

            logger.info(f"Checkpoint restored: {data.get('name')} ({restored} files)")
            return True
        except Exception as e:
            logger.error(f"Checkpoint restore failed: {e}")
            return False

    def list_checkpoints(self) -> list[dict]:
        results = []
        for cp_path in CHECKPOINT_DIR.glob("cp_*.json"):
            try:
                with open(cp_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                results.append({
                    "id": data["id"], "name": data["name"],
                    "description": data["description"], "files": len(data.get("files", {})),
                    "created": data["created"],
                })
            except Exception:
                pass
        return sorted(results, key=lambda x: x["created"], reverse=True)