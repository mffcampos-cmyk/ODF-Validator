from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from .filetype import classify_file

MANAGED_DIR_NAMES = {"rules", ".drafts", "_reference", ".incoming"}
MANIFEST_FILE_NAME = "pack.yaml"


@dataclass
class ScanResult:
    ruleset_dir: Path
    xsd_files: list[Path] = field(default_factory=list)
    code_files: list[Path] = field(default_factory=list)
    dd_files: list[tuple[Path, str | None]] = field(default_factory=list)
    unknown_files: list[Path] = field(default_factory=list)


def _is_managed(path: Path, ruleset_dir: Path) -> bool:
    # Any dotfile, rather than a list of the state files that exist today.
    # This WAS such a list -- .ingestion_state.json and .dd_obligations.json
    # by name -- the sync feature added .sources.json without touching it,
    # and the next import reported the app's own provenance file as an
    # unrecognised source document. No IOC document is ever a dotfile, so
    # the leading dot is the durable rule and the next cache file the app
    # invents cannot reopen this.
    if path.name.startswith("."):
        return True
    if path.name == MANIFEST_FILE_NAME and path.parent == ruleset_dir:
        return True
    parent_parts = path.relative_to(ruleset_dir).parts[:-1]
    return any(part in MANAGED_DIR_NAMES for part in parent_parts)


def _discipline_for(path: Path, ruleset_dir: Path) -> str | None:
    parts = path.relative_to(ruleset_dir).parts
    if "Disciplines" in parts:
        idx = parts.index("Disciplines")
        if idx + 2 < len(parts):
            return parts[idx + 1]
    return None


def scan_ruleset(ruleset_dir: Path) -> ScanResult:
    """Recursively type every source file under a ruleset folder, skipping the
    app-managed rules/, .drafts/ and .incoming/ subfolders, human-facing
    _reference/ subfolders, and every dotfile (the app's own state and cache
    files -- see _is_managed)."""
    result = ScanResult(ruleset_dir=ruleset_dir)
    for path in sorted(ruleset_dir.rglob("*")):
        if not path.is_file() or _is_managed(path, ruleset_dir):
            continue
        kind = classify_file(path)
        if kind == "xsd":
            result.xsd_files.append(path)
        elif kind == "codes":
            result.code_files.append(path)
        elif kind == "dd":
            result.dd_files.append((path, _discipline_for(path, ruleset_dir)))
        else:
            result.unknown_files.append(path)
    return result
