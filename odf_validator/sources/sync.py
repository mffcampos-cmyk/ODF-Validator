from __future__ import annotations
import io
import json
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath, PureWindowsPath

import httpx
import yaml

from .catalogue import (CatalogueEntry, has_directory_component,
                        parse_catalogue)
from .fetch import SourceFetchError, get
from .provenance import (SOURCES_FILE_NAME, Provenance, SourceRecord,
                         hash_bytes, utc_now)

INCOMING_DIR_NAME = ".incoming"

# The staging manifest's filename, living directly under .incoming/. It sits
# inside the app-managed staging directory on purpose: .incoming is already
# in scanner.MANAGED_DIR_NAMES (any path with an .incoming/ ancestor is
# skipped by scan_ruleset), and _is_managed's check walks EVERY ancestor
# component of a path, not just its immediate parent -- so a file sitting
# directly inside .incoming/, like this one, is excluded the same way an
# extracted archive member nested two levels deeper is. No scanner change
# was needed; this only needed confirming.
INCOMING_MANIFEST_NAME = "manifest.json"


@dataclass
class EntryStatus:
    entry: CatalogueEntry
    state: str                       # see SyncReport docstring
    local_reference: str | None = None
    local_published: date | None = None


@dataclass
class SyncReport:
    """What one ruleset's sources look like against the upstream page.

    States:
      current           held, and confirmed to match upstream
      unverified        held, but adopted rather than fetched -- we know the
                        bytes, not which upstream version they are
      update            upstream has moved on
      new               published upstream, nothing held locally
      missing-upstream  held locally, no longer on the page
      unknown           announced on the page with no downloadable artifact
      not-configured    (report level) no source.index_url in pack.yaml
    """
    pack: str
    configured: bool
    entries: list[EntryStatus] = field(default_factory=list)
    error: str | None = None
    last_checked: str | None = None

    @property
    def updates(self) -> list[EntryStatus]:
        return [s for s in self.entries if s.state in ("update", "new")]


@dataclass
class StagedEntry:
    """What a staged file under .incoming/ IS -- enough of its original
    CatalogueEntry that apply_targets can write a truthful provenance
    record later without asking the network or a live catalogue for
    anything. One of these is written to the manifest (see
    `INCOMING_MANIFEST_NAME`) alongside every file `fetch_targets` stages.

    Keyed in the manifest dict by the file's eventual ruleset-relative
    path -- i.e. the same string both `fetch_targets` (for a direct
    document, `entry.target`; for an archive member, the member's own
    destination relative to `.incoming/`) and `apply_targets` (as `rel`)
    already compute, so no new addressing scheme was invented.
    """
    url: str
    reference: str
    published: date | None
    kind: str
    target: str
    discipline: str | None
    title: str

    @classmethod
    def from_entry(cls, entry: CatalogueEntry) -> "StagedEntry":
        return cls(url=entry.url, reference=entry.reference,
                   published=entry.published, kind=entry.kind,
                   target=entry.target, discipline=entry.discipline,
                   title=entry.title)

    def as_catalogue_entry(self) -> CatalogueEntry:
        return CatalogueEntry(reference=self.reference, title=self.title,
                              published=self.published, kind=self.kind,
                              url=self.url, target=self.target,
                              discipline=self.discipline)

    def to_json(self) -> dict:
        return {"url": self.url,
                "reference": self.reference,
                "published": self.published.isoformat() if self.published else None,
                "kind": self.kind,
                "target": self.target,
                "discipline": self.discipline,
                "title": self.title}

    @classmethod
    def from_json(cls, data: dict) -> "StagedEntry":
        """Mirrors SourceRecord.from_json's contract exactly: every field
        but `published` is read with `.get()` and a safe default, so the
        only way this raises is a malformed `published` date string (or a
        non-string in that field) -- (TypeError, ValueError), which the
        caller (`_load_manifest`) catches and skips, same as one bad
        provenance record does not fail the whole `.sources.json` load.
        """
        published = data.get("published")
        return cls(url=data.get("url", ""),
                   reference=data.get("reference", ""),
                   published=date.fromisoformat(published) if published else None,
                   kind=data.get("kind", ""),
                   target=data.get("target", ""),
                   discipline=data.get("discipline"),
                   title=data.get("title", ""))


def _manifest_path(incoming: Path) -> Path:
    return incoming / INCOMING_MANIFEST_NAME


def _load_manifest(incoming: Path) -> dict[str, StagedEntry]:
    """Tolerant load, the same contract as Provenance.load: a missing,
    empty, or unparsable manifest degrades to "nothing staged is described"
    rather than raising, and one malformed record within an otherwise-valid
    file is skipped rather than failing the whole load.
    """
    path = _manifest_path(incoming)
    records: dict[str, StagedEntry] = {}
    try:
        if not path.exists():
            return records
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return records
    if not isinstance(data, dict):
        return records
    raw = data.get("entries")
    if not isinstance(raw, dict):
        return records
    for key, rec in raw.items():
        if not isinstance(rec, dict):
            continue
        try:
            records[key] = StagedEntry.from_json(rec)
        except (TypeError, ValueError):
            continue
    return records


def _save_manifest(incoming: Path, manifest: dict[str, StagedEntry]) -> None:
    """Best-effort persist, guarded the same way Provenance.save()'s callers
    guard it elsewhere in this module -- a full disk or a permission error
    here must not abort whatever the caller was doing when it decided to
    update the manifest; it just costs that one manifest entry.

    An EMPTY manifest deletes the file outright rather than writing '{}'.
    Without this, a manifest.json left behind with no entries would make
    `.incoming/` look permanently non-empty to `_prune_empty_dirs`'s
    `any(incoming.iterdir())` check, and the staging directory -- which is
    otherwise supposed to vanish once nothing is staged -- would never be
    removed.
    """
    path = _manifest_path(incoming)
    try:
        if not manifest:
            if path.exists():
                path.unlink()
            return
        incoming.mkdir(parents=True, exist_ok=True)
        payload = {"entries": {k: v.to_json() for k, v in manifest.items()}}
        path.write_text(json.dumps(payload, indent=2, sort_keys=True),
                        encoding="utf-8")
    except OSError:
        pass


def _reconcile_manifest(incoming: Path) -> dict[str, StagedEntry]:
    """The manifest, with any record whose staged file no longer exists
    dropped -- and the drop persisted, best-effort, if anything changed.

    A manifest record is only useful as long as the file it describes is
    still sitting in .incoming/: once that file is gone (a user deleted it
    by hand, or -- see apply_targets -- a promotion's own manifest cleanup
    lost a race with a crash) the record is stale bookkeeping, not evidence
    of a problem worth preserving for a human to notice. That is a
    deliberately different stance from `_confined`'s toward an unconfinable
    provenance `target`: THAT keeps the bad record because dropping it
    would hide corruption in `.sources.json`. A manifest record naming a
    file that simply is not there is not corruption, just staleness, and
    self-heals here.

    `is_file()` swallows ENOENT/ENOTDIR but can still raise for EACCES (see
    `_staged_for`'s docstring for the same distinction) -- a permission
    error querying one path is treated as "cannot currently confirm this is
    gone", not as "gone", so a transient EACCES cannot delete a record for
    a file that is, in fact, still there.
    """
    manifest = _load_manifest(incoming)
    survivors: dict[str, StagedEntry] = {}
    dirty = False
    for key, record in manifest.items():
        try:
            exists = (incoming / key).is_file()
        except OSError:
            exists = True
        if exists:
            survivors[key] = record
        else:
            dirty = True
    if dirty:
        _save_manifest(incoming, survivors)
    return survivors


def staged_entries(ruleset_dir: Path) -> list[CatalogueEntry]:
    """Every CatalogueEntry apply_targets could promote right now, built
    entirely from the .incoming/ manifest -- no catalogue fetch, no
    network, and independent of whatever `check()` last reported (which
    may be stale, or may never have completed at all on an offline
    machine). This is what /sources/apply uses instead of a live report's
    entries; apply_targets itself keeps taking a plain entries list so its
    existing callers and tests are unaffected.

    Several manifest records can share one (url, target) pair -- every
    member of one staged archive has its own record, but they all describe
    the same original archive entry. They collapse to a single
    CatalogueEntry here: apply_targets' `_staged_for` already scans the
    whole target directory for an archive entry, so passing one member's
    worth of duplicate entries would only run `_retire_superseded`
    redundantly for no benefit.
    """
    incoming = ruleset_dir / INCOMING_DIR_NAME
    manifest = _reconcile_manifest(incoming)
    seen: dict[tuple[str, str], CatalogueEntry] = {}
    for key, record in manifest.items():
        # The manifest is JSON sitting in the user's own repo, so its keys
        # and targets are untrusted the same way a provenance target is.
        # Both become paths: the key locates the staged file under
        # .incoming/, and the target is where apply_targets writes and what
        # _retire_superseded may delete. `_confined` already guards the
        # delete; without the same check here a hand-edited or corrupted
        # manifest naming '../../../../etc/x' would have _staged_for resolve
        # the "staged file" to that path, copy it onto itself, and then
        # unlink it -- deleting an arbitrary file outside the ruleset.
        # Verified reachable before this guard existed.
        if _confined(ruleset_dir, key) is None:
            continue
        if _confined(ruleset_dir, record.target) is None:
            continue
        seen.setdefault((record.url, record.target),
                        record.as_catalogue_entry())
    return list(seen.values())


def orphaned_staged_files(ruleset_dir: Path) -> list[str]:
    """Staged files under .incoming/ that no manifest record describes.

    This happens two ways: a file staged by a build that predates the
    manifest, or a manifest that was lost/corrupted after staging. Either
    way, `staged_entries()` cannot reconstruct a CatalogueEntry for it, so
    apply_targets is never even asked to promote it -- writing a
    provenance record with a fabricated url/reference/published would be
    untruthful, and this module does not do that. But leaving the file
    silently stuck in .incoming/ forever is exactly the "indistinguishable
    from nothing staged" failure this whole fix exists to remove. So it is
    named here instead, for a caller (the /sources/apply route) to surface
    to a human -- the same "make it visible, do not vanish it" stance
    `_retire_superseded` takes toward an unconfinable provenance target.
    """
    incoming = ruleset_dir / INCOMING_DIR_NAME
    try:
        if not incoming.is_dir():
            return []
        known = set(_reconcile_manifest(incoming))
        orphans = []
        for path in sorted(incoming.rglob("*")):
            if not path.is_file():
                continue
            if path == _manifest_path(incoming):
                continue
            rel = path.relative_to(incoming).as_posix()
            if rel not in known:
                orphans.append(rel)
        return orphans
    except OSError:
        return []


def read_source_config(ruleset_dir: Path) -> dict:
    """pack.yaml's `source` block, or {} if there is none to read.

    `exists()` is inside the try along with the read and the YAML parse:
    pathlib only swallows ENOENT/ENOTDIR/EBADF/ELOOP internally, not EACCES
    -- a ruleset directory the process cannot traverse makes `exists()`
    itself raise PermissionError, and that is exactly the same "can't read
    the manifest" situation as a missing or unparsable pack.yaml.
    """
    manifest_path = ruleset_dir / "pack.yaml"
    try:
        if not manifest_path.exists():
            return {}
        loaded = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(loaded, dict):
        return {}
    source = loaded.get("source")
    return source if isinstance(source, dict) else {}


def check(ruleset_dir: Path, *, client: httpx.Client | None = None) -> SyncReport:
    """Fetch the index page and diff it against what the ruleset holds.

    Fetches exactly one HTML page and never a document. This runs on app
    start, so the guarantee is drawn by exception type, not by pipeline
    stage: every filesystem, network, and clock operation reachable from
    here -- reading pack.yaml, loading and saving `.sources.json`,
    fetching and parsing the index page, and locating/hashing files
    already on disk during adoption -- is guarded at the point it can
    fail, narrowed to OSError (plus the fetch layer's own declared
    exception types), and turned into `report.error` or a skipped entry
    instead of raising. Being offline, a proxy truncating the response, a
    full disk, an unreadable file, or one that vanishes mid-scan are all
    ordinary operational failures, and none of them should turn into a
    startup crash.

    That guarantee stops at the exception type, not before it: a real
    defect in this module's own diff/adoption logic (e.g. an AttributeError
    from a typo) is not an OSError and is deliberately left to propagate
    loudly rather than be relabelled as an environmental failure.
    """
    config = read_source_config(ruleset_dir)
    index_url = config.get("index_url")
    if not index_url:
        return SyncReport(pack=ruleset_dir.name, configured=False)

    report = SyncReport(pack=ruleset_dir.name, configured=True)
    try:
        prov = Provenance.load(ruleset_dir / SOURCES_FILE_NAME)
    except OSError:
        # Provenance.load() documents that it never raises, but that
        # promise rests on Path.exists(), which itself raises
        # PermissionError for a directory-level EACCES rather than
        # swallowing it. sync.py does not own provenance.py, so it defends
        # its own call site: degrade to "nothing known", same as
        # Provenance.load()'s own behaviour for a missing or corrupt file,
        # rather than let the rest of check() see a half-failed startup.
        prov = Provenance(path=ruleset_dir / SOURCES_FILE_NAME)

    try:
        result = get(index_url, expect=None, client=client)
        entries = parse_catalogue(result.body.decode("utf-8", "replace"),
                                  index_url)
    except (SourceFetchError, httpx.HTTPError, ValueError) as e:
        report.error = f"Could not read the index page: {e}"
        return report
    except Exception as e:
        # parse_catalogue hands us to lxml, and lxml does not confine itself
        # to ValueError -- an empty or truncated body raises
        # lxml.etree.ParserError, and a sufficiently hostile one could raise
        # something else again. Nothing from the fetch/parse step is allowed
        # past this point uncaught, known exception type or not.
        report.error = (f"Could not read the index page: unexpected "
                        f"{type(e).__name__}: {e}")
        return report

    # The status/orphan diffing from here to prov.save() is this module's
    # own logic, not I/O, and is deliberately left uncaught so a real bug
    # here (e.g. an AttributeError from a typo) stays loud. _adopt_existing
    # does touch the filesystem, but guards each entry's own I/O narrowly
    # by OSError internally -- see its docstring -- rather than being
    # wrapped here, so a logic bug inside it still propagates too.
    if not prov.records:
        _adopt_existing(ruleset_dir, entries, prov)

    for entry in entries:
        report.entries.append(_status_for(ruleset_dir, entry, prov))

    _mark_missing_upstream(entries, prov, report)

    prov.last_checked = utc_now()
    report.last_checked = prov.last_checked

    try:
        prov.save()
    except Exception as e:
        # Persisting is environmental I/O again (a full disk, a permission
        # error on .sources.json -- both real failure modes on this
        # project's own state files, not hypothetical). The diff above
        # already succeeded, so the report keeps the entries it computed;
        # only the write failed, which costs a redundant re-adopt or
        # re-fetch on the next check rather than a startup crash. The
        # message is deliberately distinct from the fetch/parse error above
        # so the two failure stages are distinguishable in the report.
        report.error = f"Could not persist source state: {e}"

    return report


def _adopt_existing(ruleset_dir: Path, entries: list[CatalogueEntry],
                    prov: Provenance) -> None:
    """Record files already sitting in the ruleset, without claiming they are
    current. See the spec: reference and published stay None deliberately.

    Finding and hashing that file is filesystem I/O like anything else in
    this module: `_local_file_for` calls `is_dir()` and `iterdir()`, which
    raise PermissionError for a directory the process cannot list, and
    `read_bytes()` raises PermissionError for a file it cannot read or
    FileNotFoundError if the file is removed between the directory scan
    above and this read (TOCTOU). One bad file among many is not a reason
    to abort the whole adoption pass, so each entry is handled on its own
    -- but a file that could not actually be hashed must not be recorded as
    adopted either. It is simply left out of `prov`: `_status_for` then
    reports it as "new", exactly as if nothing were on disk yet, and it is
    retried on the next check.
    """
    for entry in entries:
        if entry.kind == "unknown":
            continue
        try:
            local = _local_file_for(ruleset_dir, entry)
            if local is None:
                continue
            digest = hash_bytes(local.read_bytes())
        except OSError:
            continue
        rel = local.relative_to(ruleset_dir).as_posix()
        prov.put(rel, SourceRecord(url=entry.url, reference=None,
                                   published=None, sha256=digest,
                                   adopted=True))


def _local_file_for(ruleset_dir: Path, entry: CatalogueEntry) -> Path | None:
    """The file already holding this entry's document, if any.

    Matching is by filename stem within the target directory, so a
    hand-converted ODF_GEN_R-OWG2026-GEN.md satisfies the .pdf entry the site
    publishes. For an archive entry (target ends in '/') any file in the
    target directory counts -- the archive's members are what we hold, and
    their names carry versions we did not choose.
    """
    if entry.target.endswith("/"):
        directory = ruleset_dir / entry.target.rstrip("/")
        if not directory.is_dir():
            return None
        members = sorted(p for p in directory.iterdir() if p.is_file())
        return members[0] if members else None

    target = ruleset_dir / entry.target
    directory = target.parent
    if not directory.is_dir():
        return None
    for candidate in sorted(directory.iterdir()):
        if candidate.is_file() and candidate.stem == target.stem:
            return candidate
    return None


def _status_for(ruleset_dir: Path, entry: CatalogueEntry,
                prov: Provenance) -> EntryStatus:
    if entry.kind == "unknown":
        return EntryStatus(entry, "unknown")

    record, _ = _record_for(ruleset_dir, entry, prov)
    if record is None:
        return EntryStatus(entry, "new")
    if record.stale:
        return EntryStatus(entry, "update", record.reference, record.published)
    if record.adopted or record.reference is None:
        return EntryStatus(entry, "unverified")
    if (record.reference != entry.reference
            or record.published != entry.published):
        return EntryStatus(entry, "update", record.reference, record.published)
    return EntryStatus(entry, "current", record.reference, record.published)


def _record_for(ruleset_dir: Path, entry: CatalogueEntry,
                prov: Provenance) -> tuple[SourceRecord | None, str | None]:
    """The provenance record covering this entry, and the target path it sits
    at. An archive entry's record is keyed by an extracted member's path, not
    by the archive, so it is found by URL rather than by target."""
    if not entry.target.endswith("/"):
        rel = entry.target
        direct = prov.get(rel)
        if direct is not None:
            return direct, rel
        # An adopted .md standing in for a .pdf entry is keyed by its own
        # name. Adoption records that record with THIS entry's url (see
        # _adopt_existing), so requiring the url to match still finds it --
        # while refusing to bind an unrelated same-stem leftover (e.g. a
        # stale Notes.md) to a brand-new, differently-sourced Notes.pdf entry.
        stem = Path(entry.target).stem
        parent = Path(entry.target).parent.as_posix()
        for target, record in prov.records.items():
            same_dir = Path(target).parent.as_posix() == parent
            if (same_dir and Path(target).stem == stem
                    and record.url == entry.url):
                return record, target
        return None, None

    return _best_archive_record(ruleset_dir, entry, prov)


def _best_archive_record(ruleset_dir: Path, entry: CatalogueEntry,
                         prov: Provenance) -> tuple[SourceRecord | None, str | None]:
    """Among every record sharing this archive entry's url, the one that
    actually represents it.

    Under normal operation there is only ever one: `_retire_superseded`
    drops the old target's record the moment the new one lands (Common
    Codes v2.1 -> v2.2). Several records can share a url only when that
    retirement did not complete cleanly:

    - `_retire_superseded` deliberately KEEPS a record it refuses to
      retire (see its docstring) -- a hand-edited or corrupted `target`
      that fails `_confined`'s check. That record is retained so the
      problem keeps surfacing on every run, not so it gets mistaken for
      the real thing here. Iterating `prov.records` (a dict, alphabetical
      by key after a save/load round-trip) in plain insertion order and
      returning the first match -- the bug this function fixes -- let a
      refused record with an earlier-sorting key (e.g.
      'codes/AAA_evil/...') shadow the freshly-promoted real one
      ('codes/SYOG2026_...'), so `check()` reported a just-fetched archive
      as 'unverified'.
    - A crash between writing the new record and dropping the old one
      (apply_targets persists after each step) can leave both legitimately
      confined records momentarily, until the next run finishes the
      retirement.

    So: records whose target `_confined` refuses are excluded first --
    those are exactly the ones that must never be mistaken for the live
    record, the same test `_retire_superseded` already applies before
    touching disk. Among what is left, the one with the latest
    `fetched_at` wins -- an adopted record (no real fetch, `fetched_at` is
    None) sorts below any record that was actually fetched, and between
    two genuinely fetched records the newer one is the current state. The
    target name is a last-resort, deterministic tiebreaker. If NOTHING
    matching is confined (every record sharing this url is unusable), the
    same latest-`fetched_at` rule is applied to the unconfined records
    instead, rather than reporting 'new' for an entry that provenance
    does, in fact, have something recorded for. Degraded either way, but
    returning the freshest of a bad set beats returning an arbitrary one.
    """
    matches = [(target, record) for target, record in prov.records.items()
              if record.url == entry.url]
    if not matches:
        return None, None
    confined = [(target, record) for target, record in matches
               if _confined(ruleset_dir, target) is not None]
    candidates = confined or matches
    best_target, best_record = max(
        candidates, key=lambda item: (item[1].fetched_at or "", item[0]))
    return best_record, best_target


def _mark_missing_upstream(entries: list[CatalogueEntry], prov: Provenance,
                           report: SyncReport) -> None:
    """Held locally, no longer published. Reported, never deleted: the IOC
    restructuring its site is not a reason to destroy source documents."""
    live_urls = {e.url for e in entries if e.url}
    for target, record in sorted(prov.records.items()):
        if record.url and record.url not in live_urls:
            orphan = CatalogueEntry(
                reference=record.reference or "", title=target,
                published=record.published, kind="unknown", url=record.url,
                target=target, discipline=None)
            report.entries.append(EntryStatus(orphan, "missing-upstream",
                                              record.reference,
                                              record.published))


def verify_targets(ruleset_dir: Path, entries: list[CatalogueEntry], *,
                   client: httpx.Client | None = None) -> dict[str, str]:
    """Settle 'unverified' entries with one conditional GET each.

    Bytes matching what provenance recorded means the local copy IS upstream's
    current one, so the entry is promoted to 'current' and gains the
    reference, date and validators it was adopted without. Bytes differing
    means stale -- flagged explicitly rather than by reference comparison,
    because a reference like YOG-2026-SWM is the same string on every revision
    of that document.

    The local file is never touched here; this only reads.
    """
    try:
        prov = Provenance.load(ruleset_dir / SOURCES_FILE_NAME)
    except OSError:
        # Same defensive call-site guard as check() and apply_targets():
        # Provenance.load() documents that it never raises, but that rests
        # on Path.exists(), which itself raises for a directory-level
        # EACCES. Degrade to "nothing known" -- every entry below then
        # finds no record and is skipped, same as the documented "no
        # provenance record" case, rather than the whole call blowing up.
        prov = Provenance(path=ruleset_dir / SOURCES_FILE_NAME)
    resolved: dict[str, str] = {}

    for entry in entries:
        if entry.kind == "unknown" or not entry.url:
            continue
        record, target = _record_for(ruleset_dir, entry, prov)
        if record is None or target is None:
            continue
        if not (record.adopted or record.reference is None):
            continue

        try:
            result = get(entry.url, etag=record.etag,
                         last_modified=record.last_modified,
                         expect=entry.kind, client=client)
        except (SourceFetchError, httpx.HTTPError):
            continue
        if result.status != 200 or not result.body:
            continue
        # `not result.body`, not `is None`: a 304 gives None, but a 200 with
        # an empty body gives b"", which is falsy and must be treated the
        # same way. Hashing b"" would almost never match what we recorded,
        # so an empty or truncated response would have been reported as
        # `stale` -- a false "your copy is out of date" from a transport
        # failure. Leaving the entry `unverified` is the honest answer.

        if hash_bytes(result.body) == record.sha256:
            new_record = SourceRecord(
                url=entry.url, reference=entry.reference,
                published=entry.published, sha256=record.sha256,
                etag=result.etag, last_modified=result.last_modified,
                fetched_at=utc_now(), adopted=False, stale=False)
            new_state = "current"
        else:
            new_record = SourceRecord(
                url=entry.url, reference=record.reference,
                published=record.published, sha256=record.sha256,
                etag=record.etag, last_modified=record.last_modified,
                fetched_at=record.fetched_at, adopted=False, stale=True)
            new_state = "update"

        prov.put(target, new_record)
        try:
            prov.save()
        except OSError:
            # Persisting is environmental I/O, same class of failure
            # check() guards around its own prov.save() call (a full disk,
            # a permission error on .sources.json). The resolution was
            # computed correctly but did not survive to disk, so this
            # entry must not be reported as resolved -- the next
            # verify_targets() call re-derives it from a fresh load
            # instead of the caller believing a state that never
            # persisted. Other entries in this run are unaffected.
            continue
        resolved[entry.target] = new_state

    return resolved


def fetch_targets(ruleset_dir: Path, entries: list[CatalogueEntry], *,
                  client: httpx.Client | None = None) -> list[str]:
    """Download the given entries into .incoming/, mirroring the live layout.

    Archives are extracted here, so .incoming/codes/ holds the .xlsx and the
    .zip is never stored. Nothing in the live tree is touched. One document
    failing does not abort the rest -- a single 404 upstream should not block
    the other twenty-nine.

    Failures are narrowed the same way as check(): a fetch failure
    (SourceFetchError / httpx.HTTPError) or a filesystem failure writing the
    staged bytes (OSError -- a full disk, a permission error, a directory
    that cannot be created) skips that one entry rather than aborting the
    rest. A blanket `except Exception` is deliberately not used here: it
    would also swallow a real bug in this function's own logic.

    Every file landed here also gets a manifest record (see
    `INCOMING_MANIFEST_NAME` / `StagedEntry`) recording what it IS -- so
    apply_targets can promote it later without any network call or live
    catalogue, including after a restart with no upstream reachable at
    all. The manifest is loaded once, updated in memory as files stage,
    and saved once at the end; a manifest write failure is swallowed the
    same way `_save_manifest` always swallows one (OSError), so a full
    disk costs that file its manifest record -- see
    `orphaned_staged_files` for what happens to it then -- not the rest of
    this fetch.
    """
    incoming = ruleset_dir / INCOMING_DIR_NAME
    manifest = _reconcile_manifest(incoming)
    staged: list[str] = []
    for entry in entries:
        if entry.kind == "unknown" or not entry.url:
            continue
        try:
            result = get(entry.url, expect=entry.kind, client=client)
        except (SourceFetchError, httpx.HTTPError):
            continue
        if result.status != 200 or not result.body:
            continue
        # Falsy, not `is None` -- see verify_targets. A 200 with an empty
        # body would otherwise stage a zero-byte document, and applying it
        # would overwrite a good local file with nothing.

        if entry.target.endswith("/"):
            members = _stage_archive(incoming, ruleset_dir, entry, result.body)
            staged.extend(members)
            for m in members:
                # `m` is ruleset-relative (".incoming/codes/x.xlsx"); the
                # manifest key is relative to .incoming/ itself, matching
                # what apply_targets computes as `rel`.
                key = m[len(INCOMING_DIR_NAME) + 1:]
                manifest[key] = StagedEntry.from_entry(entry)
        else:
            # CRITICAL 2 (final whole-branch review), defence in depth:
            # catalogue._classify now refuses to hand back a "general"
            # target with a directory component (see has_directory_component
            # there), so entry.target should never be able to escape
            # `incoming` by the time it reaches here. This confines it
            # anyway -- one path-derived-from-untrusted-input write site
            # left unconfined is one too many.
            #
            # TWO checks, not one, because they cover different halves of
            # the same class and neither alone is host-independent:
            #
            # - A literal backslash anywhere in `target` is refused outright.
            #   No legitimate target this module ever produces contains one
            #   (a "dd" target's own directory component is always
            #   forward-slash: "Disciplines/SWM/x.pdf"), so this is a pure,
            #   host-independent substring check with no pathlib parsing or
            #   resolve() involved -- it catches a relative traversal like
            #   '..\\..\\..\\..\\Startup\\evil.pdf' on EVERY host,
            #   including this one, even though backslash is an ordinary
            #   filename character on POSIX and such a target would not
            #   actually escape `incoming` if written here. `_confined`
            #   alone cannot be relied on for this half: its containment
            #   check is resolve()-based, and resolve() follows the HOST's
            #   own separator rules -- on a POSIX dev/CI machine a relative
            #   backslash string resolves to one harmless same-directory
            #   file (confirmed: _confined(incoming, target) is not None for
            #   exactly this input on POSIX), even though the very same
            #   string is a real four-level escape once this code runs on
            #   Windows in production. Refusing every backslash outright
            #   sidesteps that host-dependence entirely rather than trying
            #   to out-clever resolve().
            # - `_confined` still catches everything else this substring
            #   check does not: an absolute path (POSIX or Windows/UNC form)
            #   and a forward-slash '../' traversal that genuinely escapes
            #   -- both are lexical/resolve() checks that already behave
            #   identically on either host, because forward slash is a
            #   separator under both PurePosixPath and PureWindowsPath.
            if "\\" in entry.target or _confined(incoming, entry.target) is None:
                continue
            try:
                destination = incoming / entry.target
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(result.body)
            except OSError:
                continue
            staged.append(destination.relative_to(ruleset_dir).as_posix())
            manifest[entry.target] = StagedEntry.from_entry(entry)
    _save_manifest(incoming, manifest)
    return staged


# Which archive members are worth keeping, by entry kind.
ARCHIVE_MEMBER_SUFFIXES = {"codes": {".xlsx"}, "schema": {".xsd"}}


# `has_directory_component` moved to catalogue.py -- CRITICAL 2 of the final
# whole-branch review needed the exact same host-independent check there
# too (for a "general" entry's target, derived from an untrusted index-page
# href), and this module already imports from catalogue, so catalogue is the
# one home rather than two copies of the same logic drifting apart.
_has_directory_component = has_directory_component


def _stage_archive(incoming: Path, ruleset_dir: Path, entry: CatalogueEntry,
                   body: bytes) -> list[str]:
    """Extract the wanted members of one archive into the staging layout.

    Members are filtered before anything is written: only files whose
    extension matches the entry's kind are kept, a member with any
    directory component is refused outright (the traversal guard below),
    and a corrupt archive or a corrupt individual member is skipped rather
    than aborting the whole entry -- the same "one failure does not abort
    the rest" reasoning as fetch_targets applies within a single archive
    too: a bad CRC-32 on one member is data-level corruption caught by
    archive.read(), and should not cost us the other members that
    decompress fine. (Central-directory truncation is a different case --
    it fails at the zipfile.ZipFile() constructor below, before any member
    can be read, so it costs the whole archive rather than just one entry.)
    """
    wanted = ARCHIVE_MEMBER_SUFFIXES.get(entry.kind, set())
    directory = incoming / entry.target.rstrip("/")
    staged: list[str] = []
    try:
        archive = zipfile.ZipFile(io.BytesIO(body))
    except zipfile.BadZipFile:
        return staged

    with archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            if _has_directory_component(member.filename):
                # A member with any directory component -- '../../evil.xlsx',
                # 'nested/x.xlsx', '..\\..\\evil.xlsx', 'C:\\evil.xlsx', an
                # absolute path. The published archives are flat, so this is
                # either a malformed archive or an attempt to write outside
                # the staging folder. Refuse it; do not flatten it to a bare
                # filename and unpack it anyway.
                continue
            name = member.filename
            if Path(name).suffix.lower() not in wanted:
                continue
            destination = directory / name
            try:
                directory.mkdir(parents=True, exist_ok=True)
                data = archive.read(member)
                destination.write_bytes(data)
            except (OSError, zipfile.BadZipFile):
                # A single truncated/corrupt member, or a filesystem failure
                # writing it, does not cost us the rest of the archive.
                continue
            rel = destination.relative_to(ruleset_dir).as_posix()
            if rel not in staged:
                # Two members (or two catalogue entries) can stage to the
                # same destination path; only the second write's bytes
                # survive on disk. Reporting the path twice here would be
                # actively misleading -- apply_targets (a later task)
                # consumes `staged` to promote files, and a duplicate entry
                # would promote the same already-promoted file a second
                # time for no reason.
                staged.append(rel)
    return staged


def apply_targets(ruleset_dir: Path, entries: list[CatalogueEntry]) -> list[str]:
    """Promote staged files (see fetch_targets) into the live ruleset tree.

    Per-target, not transactional: entries and their staged files are
    processed one at a time, and provenance is persisted after each one
    commits, so a crash or an environmental failure part-way through leaves
    a coherent, resumable state rather than a half-written batch.

    The critical ordering guarantee: a staged file is only ever unlinked
    from .incoming/ AFTER its bytes are live at the destination, the file it
    superseded (if any) has been retired, and .sources.json has been saved
    to reflect all of that. Every one of those steps can fail (see the
    filesystem calls enumerated in the helpers below) -- an unwritable
    destination, a full disk, a permission error deleting the superseded
    file, a permission error persisting .sources.json. Whichever one fails,
    the staged copy is still sitting in .incoming/ afterwards, untouched,
    so calling apply_targets again retries that exact target from scratch.
    Nothing here ever deletes the staged source before the promotion it
    represents has fully committed.

    Only OSError is caught: a real defect in this function's own logic
    (a typo producing an AttributeError, say) is deliberately left to
    propagate rather than be relabelled as an environmental failure -- the
    same discipline check() and fetch_targets() already apply.

    No rebuild is triggered here. .ingestion_state.json is keyed by content
    hash, so the existing pipeline sees the changed file by itself.

    The signature is unchanged (a plain `entries` list, no manifest, no
    ruleset_dir-only overload) on purpose: an existing test suite calls
    this directly with hand-built CatalogueEntry objects and no manifest
    on disk at all, and that must keep working exactly as before. What
    changed is that entries no longer have to come from a live catalogue
    -- see `staged_entries()`, which reconstructs them from the manifest
    for a caller (the /sources/apply route) that wants to apply without
    the network. This function does not care where its `entries` came
    from.

    The one manifest-related thing this function DOES do is cleanup: once
    a staged file's promotion has fully committed (after the unlink
    above), its manifest record, if any, is dropped -- best-effort, and
    deliberately AFTER the unlink so it can never block or roll back a
    promotion that has already succeeded. A crash between the unlink and
    this cleanup leaves a manifest record pointing at a now-missing file;
    `_reconcile_manifest` (run at the top of every fetch_targets /
    staged_entries / orphaned_staged_files call) garbage-collects exactly
    that case on its own next read, so the manifest self-heals rather than
    needing a special "already-applied but not yet cleaned up" state here.
    """
    incoming = ruleset_dir / INCOMING_DIR_NAME
    try:
        prov = Provenance.load(ruleset_dir / SOURCES_FILE_NAME)
    except OSError:
        # Same defensive call-site guard as check(): Provenance.load()
        # documents that it never raises, but that rests on Path.exists(),
        # which itself raises for a directory-level EACCES. Degrade to
        # "nothing known" rather than let apply_targets blow up on entry.
        prov = Provenance(path=ruleset_dir / SOURCES_FILE_NAME)
    manifest = _reconcile_manifest(incoming)

    applied: list[str] = []
    for entry in entries:
        for staged in _staged_for(incoming, entry, manifest):
            rel = staged.relative_to(incoming).as_posix()
            destination = ruleset_dir / rel
            try:
                body = staged.read_bytes()
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(body)
                _retire_superseded(ruleset_dir, entry, prov, keep=rel)
                prov.put(rel, SourceRecord(url=entry.url,
                                           reference=entry.reference,
                                           published=entry.published,
                                           sha256=hash_bytes(body),
                                           fetched_at=utc_now(),
                                           adopted=False, stale=False))
                prov.save()
                staged.unlink()
            except OSError:
                # Any filesystem step above failed: the staged file has
                # deliberately not been unlinked yet (see the ordering
                # guarantee in the docstring), so this target is untouched
                # and safe to retry on the next apply_targets() call. Move
                # on to the next staged file / entry rather than aborting
                # the whole run over one bad target.
                continue
            # The promotion has fully committed; this staged file is gone.
            # Drop its manifest record (if any -- there may be none, e.g. a
            # file staged by an older build) and persist that immediately,
            # same "resumable after a crash" spirit as prov.save() above,
            # but never allowed to turn a completed promotion into a
            # reported failure: `applied.append` below always runs.
            if manifest.pop(rel, None) is not None:
                _save_manifest(incoming, manifest)
            applied.append(rel)

    _prune_empty_dirs(incoming)
    return applied


def _staged_for(incoming: Path, entry: CatalogueEntry,
                manifest: dict[str, StagedEntry]) -> list[Path]:
    """The staged file(s) waiting under .incoming/ for this entry, if any.

    CRITICAL (final whole-branch review): this used to glob the archive
    entry's whole staging directory with iterdir() and never consult the
    manifest at all -- so a leftover file dropped there by an older build,
    or left behind by a lost/corrupted manifest (exactly the case
    `orphaned_staged_files` exists to name), was treated as if it were a
    genuine member of THIS entry: promoted with a FABRICATED provenance
    record (this entry's own reference/published/url describing a document
    it is not), and reachable by `_retire_superseded`'s own `keep=` delete
    if it happened to sort after the real file. That bypassed the entire
    point of `_confined` and the manifest key set (see `staged_entries` and
    commits 14051fc/f73d438): those guard what CAN become a CatalogueEntry,
    but this function then went and looked at the filesystem directly
    instead of at what the manifest actually described.

    Fixed by keying off `manifest` (the same dict apply_targets already
    loaded) instead of a raw directory listing: only a file with its own
    manifest record -- naming THIS entry's url and target -- is ever
    returned. A leftover with no record is invisible here, exactly as
    `orphaned_staged_files`'s docstring already claimed ("apply_targets is
    never even asked to promote it") -- this is what makes that claim true
    for archive members too, not just single documents.

    Backward-compat carve-out, unchanged from before this fix: when
    `manifest` is EMPTY -- no manifest.json at all, e.g. an existing test
    suite calling apply_targets directly with hand-built CatalogueEntry
    objects and files placed by hand, never through fetch_targets -- there
    is nothing to key off, so this falls back to the original directory
    scan / single-file check. apply_targets' own docstring documents that
    contract must keep working exactly as before. The moment ANY manifest
    record exists, promotion becomes manifest-driven and an untracked file
    is never blindly trusted again, even one sitting right next to a
    tracked one.

    `is_dir()`/`is_file()` swallow ENOENT/ENOTDIR (a normal "nothing staged
    yet" state -- .incoming/ itself may not exist at all) but not EACCES, and
    `iterdir()` can raise for a directory this process cannot list. None of
    that is worth aborting the whole apply run over: it just means this
    entry's staged file(s), if any exist, cannot currently be seen, so they
    are treated the same as "nothing staged" and picked up on a later call.
    """
    try:
        if not manifest:
            if entry.target.endswith("/"):
                directory = incoming / entry.target.rstrip("/")
                if not directory.is_dir():
                    return []
                return sorted(p for p in directory.iterdir() if p.is_file())
            candidate = incoming / entry.target
            return [candidate] if candidate.is_file() else []

        # Manifest-driven from here down. `manifest` is apply_targets' OWN
        # raw load (_reconcile_manifest), independent of whatever confining
        # a caller like staged_entries() may or may not have already done
        # to the ENTRY -- apply_targets can be, and is, called directly with
        # hand-built entries and no such pre-filtering (see its own
        # docstring). So every manifest KEY consulted here is confined
        # against `incoming` before it is ever joined into a path, exactly
        # the same precedent as staged_entries()'s own two _confined calls
        # (commit f73d438): a manifest key is plain JSON in the user's own
        # repo, never trusted just because it happens to be sitting in
        # manifest.json. Without this, a hostile key sharing this archive
        # entry's url/target -- pointing outside the ruleset via a
        # traversal or an absolute path -- would have this function return
        # that outside path as though it were a genuine staged member;
        # apply_targets would then read it, write its bytes elsewhere, and
        # (staged files are always unlinked LAST) delete the original.
        # Confirmed reachable while developing this fix, the same way
        # f73d438's own regression was.
        if entry.target.endswith("/"):
            keys = sorted(k for k, rec in manifest.items()
                         if rec.url == entry.url and rec.target == entry.target)
            paths = []
            for k in keys:
                confined = _confined(incoming, k)
                if confined is not None and confined.is_file():
                    paths.append(confined)
            return paths

        record = manifest.get(entry.target)
        if record is None or record.url != entry.url:
            return []
        candidate = _confined(incoming, entry.target)
        return [candidate] if candidate is not None and candidate.is_file() else []
    except OSError:
        return []


def _confined(ruleset_dir: Path, target: str) -> Path | None:
    """The path `target` names under `ruleset_dir`, or None if that path
    cannot be confirmed to stay inside it.

    `target` is a dict key straight out of `.sources.json` -- plain JSON
    sitting in the user's own repo, hand-editable or corruptible, and
    trusted on nothing but a URL match before this guard existed. This
    function must be TOTAL for that input: for any `str`, it must answer
    "confined" or "not confined" and never raise. Four checks:

    0. Empty (`""`) or `"."` is refused outright. Left unchecked,
       `ruleset_dir / ""` and `ruleset_dir / "."` both resolve to
       `ruleset_dir` itself, so this function would return the ruleset
       root as if it were a legitimate per-entry target -- harmless today
       (`is_file()` on a directory is False) but it silently drops that
       provenance record from consideration, the opposite of this
       module's keep-it-so-it-is-noticed stance on unusable records (see
       `_retire_superseded`). The same reasoning covers any target that
       resolves exactly to `ruleset_dir` (e.g. 'sub/..') -- checked below,
       after resolution, since it cannot be caught lexically.
    1. An absolute-path pre-check against BOTH PurePosixPath and
       PureWindowsPath, never the host-dependent bare pathlib.Path. On
       POSIX, a Windows absolute path ('C:\\Windows\\x') or a UNC path
       ('\\\\host\\share\\x') has no leading '/', so a plain
       `Path(target).is_absolute()` is False and `ruleset_dir / target`
       would silently treat it as one odd-looking relative filename --
       but this code, and the .sources.json it reads, run on Windows too,
       where that same string IS a real absolute path. It must be refused
       regardless of which OS happens to be running right now. The
       converse (a POSIX absolute path while running on Windows) is
       caught the same way via PurePosixPath.
    2. A resolve()-based containment check, which is what actually catches
       '../outside/x' and deep '../../../x' traversal: joining with '/'
       does not by itself escape `ruleset_dir` (the '..' segments are
       still lexically present in the joined path) -- only `resolve()`,
       normalizing against the real filesystem, reveals the path lands
       outside.

    Everything from the absolute-path pre-check through `resolve()` runs
    inside one try/except, because path *construction* -- not just
    resolution -- can raise on adversarial input, and both stages are
    reachable from a hand-edited or corrupted `target`:

    - `OSError`: `resolve()` is filesystem I/O (a permission error along
      the path).
    - `RuntimeError`: `resolve()` raises this specifically -- and only --
      for a symlink loop ("Symlink loop from ..."), which is not an
      `OSError` subclass. A loop planted on disk under `ruleset_dir` (or
      reachable via a traversal component) must refuse the same as any
      other unresolvable path, not crash the caller.
    - `ValueError`: an embedded NUL byte in `target` (e.g.
      '"codes/vic\x00tim.txt"') makes `resolve()` raise
      "ValueError: embedded null byte" -- confirmed empirically; pure
      construction (`PurePosixPath(target)`, `PureWindowsPath(target)`,
      plain `/` joining) does NOT raise for a NUL byte on this CPython,
      only the underlying OS path calls inside `resolve()` do. A lone
      Unicode surrogate outside the surrogateescape range (e.g. a bare
      '\\ud800') hits the same catch: `resolve()` raises
      `UnicodeEncodeError`, which IS a `ValueError` subclass, so no
      separate case is needed for it.
      (The escape above is deliberately written with a doubled backslash.
      Spelling it live put a real unpaired surrogate in this docstring's
      constant, which CPython 3.14 refuses to encode while caching the
      module -- the app failed to start at import, before any of this code
      ran. A docstring may describe such a character, never contain it.
      See tests/unit/test_module_constants_are_encodable.py.)

    Deliberately NOT caught: anything else, most importantly
    `AttributeError` -- a real defect in this function's own code (a typo)
    must still propagate loudly rather than be relabelled as "not
    confined". This tuple is narrowed to exactly what untrusted-path
    construction/resolution can raise, not a blanket `except Exception`.
    """
    if not target or target == ".":
        return None
    try:
        if (PurePosixPath(target).is_absolute()
                or PureWindowsPath(target).is_absolute()):
            return None
        candidate = ruleset_dir / target
        resolved_root = ruleset_dir.resolve()
        resolved_candidate = candidate.resolve()
    except (OSError, ValueError, RuntimeError):
        return None
    if resolved_candidate == resolved_root:
        return None
    if not resolved_candidate.is_relative_to(resolved_root):
        return None
    return candidate


def _retire_superseded(ruleset_dir: Path, entry: CatalogueEntry,
                       prov: Provenance, keep: str) -> None:
    """Delete the file this entry previously occupied, when the new one has
    landed under a different name (Common Codes v2.1 -> v2.2).

    THE THING THIS FUNCTION EXISTS TO GUARANTEE: only ever touches a path
    that provenance recorded for THIS entry's own url. A path recorded under
    a different url, and above all a path with no record at all (a
    hand-written spreadsheet a user dropped in the same folder), is never
    even considered -- it is not in `prov.records` under this url, so the
    loop below never names it, let alone deletes it.

    A second, independent guarantee: only ever touches a path that resolves
    INSIDE `ruleset_dir`. `target` is a provenance dict key, and under
    normal operation this app only ever writes safe relative targets (both
    `_adopt_existing` and `apply_targets` derive them via
    `relative_to(ruleset_dir)`) -- but `.sources.json` is plain JSON in the
    user's own repo, and a hand-edited or corrupted record naming
    '../outside/victim.txt', an absolute path, or a Windows/UNC path must
    not walk this delete outside the ruleset tree just because its url
    happens to match. See `_confined` for how that is checked.

    `stale.is_file()` and `stale.unlink()` are left unguarded here rather
    than caught locally: if either raises OSError (the file is present but
    unreadable, or deletion is refused), that must abort THIS promotion, not
    silently drop the stale record and pretend it was retired -- the caller
    catches it, and because the staged source has not been unlinked yet (see
    apply_targets' ordering guarantee), a later call retries the retirement
    from a fresh read of provenance. If the stale file is simply already
    gone (a user deleted it by hand, or a prior partial run got this far
    last time), `is_file()` is false, nothing is unlinked, and the stale
    record is still dropped -- there is nothing left to protect.
    """
    keep_suffix = Path(keep).suffix.lower()
    for target, record in list(prov.records.items()):
        if target == keep or record.url != entry.url:
            continue
        if Path(target).suffix.lower() != keep_suffix:
            # IMPORTANT (final whole-branch review): a suffix mismatch means
            # this is a hand-converted stand-in -- e.g. a hand-converted
            # ODF_GEN_R-OWG2026-GEN.md sitting in for the .pdf the site
            # actually publishes, a case _local_file_for explicitly
            # documents as supported. Such a file can never verify (its
            # hash will never equal the .pdf's), so left to the general
            # rule below it would be silently destroyed the moment the real
            # .pdf lands -- replaced by a .pdf this repo cannot always even
            # convert, since pdf_inspector is an optional dependency. Skip
            # it, the same "never delete without being sure" stance as the
            # _confined refusal below, and leave the record in place so
            # superseded_stand_ins() keeps surfacing it to a human, who can
            # remove it once satisfied the new file is good.
            #
            # This must NOT catch the case retirement exists for: Common
            # Codes v2.1 -> v2.2 is .xlsx -> .xlsx, same suffix, so that
            # comparison is skipped here and the file is still retired below
            # -- keeping both would mean the loader ingests two conflicting
            # code tables.
            continue
        stale = _confined(ruleset_dir, target)
        if stale is None:
            # Refuse and skip. The record is deliberately NOT dropped here
            # (contrast the "already gone" case above, which does drop it):
            # dropping it would silently discard the only trace that
            # something is wrong with this entry of .sources.json, and
            # since retirement is retried from a fresh read of provenance
            # on every apply_targets() call, keeping the record means the
            # next run notices and refuses again too, rather than the
            # problem being forgotten after one skip. Nothing is deleted
            # either way; the only cost is that a genuinely stale file at
            # an unconfirmable path keeps sitting there until a human
            # fixes the record.
            continue
        if stale.is_file():
            stale.unlink()
        prov.drop(target)


def superseded_stand_ins(ruleset_dir: Path,
                         entries: list[CatalogueEntry]) -> list[str]:
    """Currently-held files provenance still describes for one of `entries`'
    own url, at a DIFFERENT path than that entry's own target, with a
    DIFFERENT suffix -- i.e. exactly what `_retire_superseded`'s suffix
    guard above declines to delete. A hand-converted
    ODF_GEN_R-OWG2026-GEN.md standing in for a newly-applied .pdf is the
    running example; this is how a caller (the /sources/apply route)
    surfaces it to a human, who can remove the stand-in once satisfied the
    new file is good -- the same "make it visible, never vanish it" stance
    `orphaned_staged_files` takes toward an unrecorded staged file, and
    `_confined`'s refusal takes toward an unconfinable provenance target.

    Deliberately read-only and independent of any single apply_targets()
    run: it re-derives the answer from whatever is CURRENTLY in
    `.sources.json`, so it keeps reporting the stand-in on every call for as
    long as the operator leaves it there, rather than only the one run that
    happened to promote the new file.

    Only non-archive entries are considered -- an archive's members all
    share one suffix by construction (see ARCHIVE_MEMBER_SUFFIXES), so this
    situation cannot arise for one.
    """
    try:
        prov = Provenance.load(ruleset_dir / SOURCES_FILE_NAME)
    except OSError:
        # Same defensive call-site guard as check()/apply_targets(): degrade
        # to "nothing known" rather than raise.
        return []
    stand_ins: list[str] = []
    for entry in entries:
        if entry.target.endswith("/") or not entry.url:
            continue
        keep_suffix = Path(entry.target).suffix.lower()
        for target, record in sorted(prov.records.items()):
            if target == entry.target or record.url != entry.url:
                continue
            if Path(target).suffix.lower() == keep_suffix:
                continue
            if _confined(ruleset_dir, target) is not None:
                stand_ins.append(target)
    return stand_ins


def _prune_empty_dirs(incoming: Path) -> None:
    """Best-effort cleanup of now-empty staging directories left behind by a
    successful apply. Purely cosmetic: never allowed to affect the already-
    promoted files or the `applied` list apply_targets returns.

    Every filesystem call here is guarded narrowly by OSError and simply
    leaves that directory in place rather than raising -- covering both a
    permission error and the race where something (a concurrent
    fetch_targets() call) populates a directory between the emptiness check
    and the rmdir, which surfaces as OSError (ENOTEMPTY on POSIX, "directory
    not empty" on Windows) from rmdir() itself.
    """
    try:
        if not incoming.is_dir():
            return
        candidates = sorted(incoming.rglob("*"), reverse=True)
    except OSError:
        return
    for path in candidates:
        try:
            if path.is_dir() and not any(path.iterdir()):
                path.rmdir()
        except OSError:
            continue
    try:
        if incoming.is_dir() and not any(incoming.iterdir()):
            incoming.rmdir()
    except OSError:
        pass
