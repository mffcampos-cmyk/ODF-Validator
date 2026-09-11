"""Disk cache for parsed Data Dictionary obligations.

Converting the 24 SYOG26 PDF Data Dictionaries costs ~12s, and
`discover_packs()` runs at import time in api/app.py, so re-parsing on every
pack load would put that on every process start. Obligations are cached beside
the ruleset and recomputed only for DDs whose content hash changed.

Deliberately separate from `.ingestion_state.json`. That file records which DDs
have been mined for draft rule suggestions, and it is correct for it to skip
unchanged files -- re-suggesting the same drafts is noise. Obligations are the
opposite: they must be complete on every load, so an unchanged DD still has to
contribute. Sharing one state file would couple "already suggested" to
"already known", and the second load of a pack would validate against fewer
obligations than the first.

The cache is COMMITTED, not ignored. It is derived data, but the derivation
needs a PDF converter and not every environment has one. Leaving it untracked
made the DD-authority feature silently inert wherever pdf-inspector was
missing: 24 conversion failures at pack load and no obligations for any of the
24 PDF disciplines, so @Gen suppression quietly stopped happening. Committing
it means a checkout validates identically with or without the converter
installed, and startup skips ~12s of PDF conversion. It is written compactly
for that reason -- pretty-printing cost 250KB of a 655KB file.
"""
from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path

STORE_FILE_NAME = ".dd_obligations.json"

# Bumped whenever parse_obligations() changes what it extracts from the same
# bytes. Entries are keyed on the DD's content hash, which does NOT change when
# the parser does -- so without this a parser fix silently no-ops against a
# committed cache and the old obligations keep being served. That is exactly
# what happened on 2026-08-31: teaching the parser about per-@Code attribute
# tables changed nothing until the cache was rebuilt, because every hash still
# matched. A mismatch here is treated as a cache miss, so the DD is reparsed.
#   1 - flat (doc_type, element, attribute) -> "M"/"O"
#   2 - values may carry an @Code condition, e.g. "M@B_JUDGE"
PARSER_VERSION = 2


def _key(rel: str) -> str:
    """Normalise a relative DD path to forward slashes.

    The cache is committed, so it crosses platforms: `str(Path)` gives
    "Disciplines/SWM/x.pdf" on POSIX and "Disciplines\\SWM\\x.pdf" on Windows.
    Without normalising, every key misses on the other OS -- a full
    reconversion, and the whole file rewritten with the other separator on each
    platform switch. `.ingestion_state.json` works around the same problem by
    storing both spellings; normalising once is cleaner.
    """
    return rel.replace("\\", "/")


def _encode(ob: dict) -> list:
    return [[dt, el, at, mo] for (dt, el, at), mo in sorted(ob.items())]


def _decode(rows) -> dict:
    return {(dt, el, at): mo for dt, el, at, mo in rows}


class ObligationStore:
    """`{relative DD path: {"hash": ..., "obligations": [...]}}`."""

    def __init__(self, path: Path, data: dict | None = None):
        self.path = path
        self._data = data or {}

    @classmethod
    def load(cls, path: Path) -> "ObligationStore":
        try:
            return cls(path, json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            # A missing or corrupt cache is not an error: it just means every
            # DD is reparsed this time and the cache is rewritten.
            return cls(path, {})

    def get(self, rel: str, file_hash: str) -> dict | None:
        entry = self._data.get(_key(rel))
        if not entry or entry.get("hash") != file_hash:
            return None
        # Entries written before PARSER_VERSION existed have no "parser" key
        # and are version 1 by definition.
        if entry.get("parser", 1) != PARSER_VERSION:
            return None
        return _decode(entry.get("obligations", []))

    def put(self, rel: str, file_hash: str, obligations: dict) -> None:
        self._data[_key(rel)] = {"hash": file_hash,
                                 "parser": PARSER_VERSION,
                                 "obligations": _encode(obligations)}

    # A scan is only trusted to prune if it still accounts for most of the
    # cache. At or below this fraction the likelier explanation is a bad scan,
    # not a deleted discipline: a transient read failure once took a
    # committed 28-entry cache down to 4, silently disabling DD-over-XSD
    # suppression for 24 disciplines (found in a rules review). Deleting a
    # discipline for real means deleting far less than half the pack, so this
    # floor rarely blocks it -- except on a small cache (see
    # SMALL_CACHE_EXEMPTION below).
    MIN_KEEP_FRACTION = 0.5

    # The two ways this guard can be wrong are not equally bad. Refusing a
    # legitimate prune costs an oversized cache file and a cache_warning line
    # in the report -- annoying, visible, and fixed by a rebuild. Allowing a
    # bad prune silently deletes committed DD obligations that cannot be
    # regenerated without the optional PDF converter -- exactly the failure
    # this guard exists to prevent (28 -> 4 entries). So the
    # boundary itself is inclusive (`<=`, not `<`): a scan that accounts for
    # *exactly* MIN_KEEP_FRACTION of the cache is treated as untrustworthy,
    # not waved through.
    #
    # That inclusive boundary would otherwise break small, legitimate shrinks:
    # deleting one discipline from a two-entry pack is exactly a 1/2 shrink
    # (see test_prune_forgets_dds_no_longer_in_the_pack), and deleting one
    # from a three-entry pack keeps a below-half fraction too. Below this
    # many entries there are too few samples for a fraction to mean anything
    # -- "half" and "a third" are both just "one DD" -- so the fraction check
    # is skipped entirely for caches smaller than this.
    SMALL_CACHE_EXEMPTION = 4

    def prune(self, keep: set[str]) -> list[str]:
        """Drop entries for DDs no longer in the pack, so a removed discipline
        cannot keep contributing obligations from the cache.

        Returns the keys actually dropped. Refuses -- and returns [] -- when
        either (a) the scan saw none of the cached DDs at all (kept == 0),
        which is never trustworthy regardless of cache size, or (b) the cache
        holds at least SMALL_CACHE_EXEMPTION entries and the scan accounts
        for at most MIN_KEEP_FRACTION of them. Callers should treat a refusal
        as a signal worth reporting.
        """
        keep = {_key(k) for k in keep}
        data_keys = {_key(r) for r in self._data}
        kept = keep & data_keys
        if data_keys and (
            not kept
            or (len(self._data) >= self.SMALL_CACHE_EXEMPTION
                and len(kept) <= len(data_keys) * self.MIN_KEEP_FRACTION)
        ):
            return []
        dropped = sorted(r for r in self._data if _key(r) not in keep)
        for rel in dropped:
            del self._data[rel]
        return dropped

    def would_shrink(self, keep: set[str]) -> int:
        """How many cached DDs this scan failed to see. Non-destructive."""
        keep = {_key(k) for k in keep}
        return len([r for r in self._data if _key(r) not in keep])

    def save(self) -> None:
        """Write atomically: a crash or a full disk mid-write must not replace
        a good committed cache with a truncated one.

        Uses a uniquely-named temp file (tempfile.mkstemp) rather than a fixed
        name, because discover_packs() can run in more than one process at
        once (e.g. `uvicorn --workers N` or `--reload`). Two processes sharing
        one fixed temp path could truncate each other's in-flight write, or
        unlink each other's temp file on the error path -- exactly the
        failure this method exists to prevent. The write is flushed and
        fsynced before the rename so a power loss cannot leave a zero-length
        file at the destination; `os.replace` itself is atomic over an
        existing file on both POSIX and Windows.
        """
        tmpname = None
        try:
            fd, tmpname = tempfile.mkstemp(
                dir=str(self.path.parent), prefix=self.path.name + ".",
                suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(self._data, separators=(",", ":"),
                                    sort_keys=True))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmpname, self.path)
        except OSError:
            # A read-only pack dir must not break validation.
            if tmpname is not None:
                try:
                    os.unlink(tmpname)
                except OSError:
                    pass
