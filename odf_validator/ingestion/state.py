from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import hashlib
import json


def hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class IngestionState:
    """Tracks which source files (by relative path) have already been ingested,
    keyed by content hash, so an unchanged file is never reprocessed and any
    human review/approval of its previously-generated rules is left untouched."""
    state_path: Path
    hashes: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, state_path: Path) -> "IngestionState":
        hashes: dict[str, str] = {}
        if state_path.exists():
            try:
                data = json.loads(state_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    hashes = dict(data)
            except json.JSONDecodeError:
                pass   # corrupt state file: degrade to "everything looks changed"
        return cls(state_path=state_path, hashes=hashes)

    def is_changed(self, rel_path: str, current_hash: str) -> bool:
        return self.hashes.get(rel_path) != current_hash

    def update(self, rel_path: str, current_hash: str) -> None:
        self.hashes[rel_path] = current_hash

    def save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(self.hashes, indent=2, sort_keys=True), encoding="utf-8")
