from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
import hashlib
import json

SOURCES_FILE_NAME = ".sources.json"


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class SourceRecord:
    """What the ruleset holds at one target path, and where it came from.

    `reference` and `published` are None for an adopted record: the file was
    found already in place, so the app knows its bytes but not which upstream
    version they represent. See the spec's adoption section.
    """
    url: str
    reference: str | None
    published: date | None
    sha256: str
    etag: str | None = None
    last_modified: str | None = None
    fetched_at: str | None = None
    adopted: bool = False
    # Verified against upstream and found to differ. Needed because most
    # entries carry a reference that never moves, so "the reference matches"
    # cannot by itself mean "the bytes match".
    stale: bool = False

    def to_json(self) -> dict:
        return {"url": self.url,
                "reference": self.reference,
                "published": self.published.isoformat() if self.published else None,
                "sha256": self.sha256,
                "etag": self.etag,
                "last_modified": self.last_modified,
                "fetched_at": self.fetched_at,
                "adopted": self.adopted,
                "stale": self.stale}

    @classmethod
    def from_json(cls, data: dict) -> "SourceRecord":
        """Parse one `entries` value. Raises (TypeError, ValueError) on any
        field that is adversarial-but-JSON-valid -- e.g. a malformed
        `published` date string, or a non-string where a string is expected.
        Callers (see `Provenance.load`) are expected to catch that and skip
        the single bad record rather than let it corrupt the whole load."""
        published = data.get("published")
        return cls(url=data.get("url", ""),
                   reference=data.get("reference"),
                   published=date.fromisoformat(published) if published else None,
                   sha256=data.get("sha256", ""),
                   etag=data.get("etag"),
                   last_modified=data.get("last_modified"),
                   fetched_at=data.get("fetched_at"),
                   adopted=bool(data.get("adopted", False)),
                   stale=bool(data.get("stale", False)))


@dataclass
class Provenance:
    """`.sources.json`: which upstream document sits at each target path.

    Follows the same contract as ingestion/state.py -- `load()` never raises.
    A missing, empty, or unparsable file degrades to "nothing is known" (no
    records). Within an otherwise-valid file, one malformed entry (e.g. an
    unparsable `published` date) is skipped rather than failing the whole
    load -- every other entry is still good information, so only that one
    record is lost, costing a redundant re-fetch rather than a broken app.
    """
    path: Path
    records: dict[str, SourceRecord] = field(default_factory=dict)
    last_checked: str | None = None

    @classmethod
    def load(cls, path: Path) -> "Provenance":
        records: dict[str, SourceRecord] = {}
        last_checked = None
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}
            if isinstance(data, dict):
                last_checked = data.get("last_checked")
                raw = data.get("entries")
                if isinstance(raw, dict):
                    for target, rec in raw.items():
                        if isinstance(rec, dict):
                            try:
                                records[target] = SourceRecord.from_json(rec)
                            except (TypeError, ValueError):
                                # One record is malformed (e.g. an
                                # unparsable `published` date). Skip just
                                # that record -- the rest of the file is
                                # still good information, and losing this
                                # one costs a redundant re-fetch, not a
                                # crash.
                                continue
        return cls(path=path, records=records, last_checked=last_checked)

    def get(self, target: str) -> SourceRecord | None:
        return self.records.get(target)

    def put(self, target: str, record: SourceRecord) -> None:
        self.records[target] = record

    def drop(self, target: str) -> None:
        self.records.pop(target, None)

    def save(self) -> None:
        payload = {"last_checked": self.last_checked,
                   "entries": {t: r.to_json() for t, r in self.records.items()}}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True),
                             encoding="utf-8")
