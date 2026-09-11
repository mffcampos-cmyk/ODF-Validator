"""The obligation cache is a tracked build artifact, not scratch state.

It is derived from the Data Dictionaries, but the derivation needs a PDF
converter, and not every environment has one. Ignoring the cache made the
DD-authority feature silently inert wherever pdf-inspector was missing: 24
conversion failures at pack load, obligations for only the four Markdown
documents, and @Gen suppression quietly not happening for any of the 24 PDF
disciplines (2026-08-14 regression report).

So the cache is committed, and these tests pin the two properties that makes
sensible: it round-trips, and it is written compactly enough to live in git.
"""
import json
from pathlib import Path

from odf_validator.ingestion.obligation_store import ObligationStore

OB = {("DT_RESULT", "Competition", "Gen"): "O",
      ("DT_ENTRIES", "Competition", "Gen"): "M"}


def test_round_trips_obligations(tmp_path):
    p = tmp_path / "ob.json"
    s = ObligationStore.load(p)
    s.put("a/b.pdf", "hash1", OB)
    s.save()
    assert ObligationStore.load(p).get("a/b.pdf", "hash1") == OB


def test_entry_is_ignored_when_the_dd_changed(tmp_path):
    p = tmp_path / "ob.json"
    s = ObligationStore.load(p)
    s.put("a/b.pdf", "hash1", OB)
    s.save()
    assert ObligationStore.load(p).get("a/b.pdf", "hash2") is None


def test_saved_file_is_compact(tmp_path):
    """Pretty-printing cost 250KB of the 655KB file. A tracked artifact should
    not carry a quarter of a megabyte of indentation."""
    p = tmp_path / "ob.json"
    s = ObligationStore.load(p)
    s.put("a/b.pdf", "h", OB)
    s.save()
    text = p.read_text(encoding="utf-8")
    assert "\n" not in text.strip(), "cache should be written on one line"
    assert ": " not in text and ", " not in text, "no whitespace after separators"
    assert json.loads(text)


def test_a_corrupt_cache_is_treated_as_empty_not_fatal(tmp_path):
    p = tmp_path / "ob.json"
    p.write_text("{ not json", encoding="utf-8")
    assert ObligationStore.load(p).get("a/b.pdf", "h") is None


def test_prune_forgets_dds_no_longer_in_the_pack(tmp_path):
    p = tmp_path / "ob.json"
    s = ObligationStore.load(p)
    s.put("keep.pdf", "h", OB)
    s.put("gone.pdf", "h", OB)
    s.prune({"keep.pdf"})
    s.save()
    reloaded = ObligationStore.load(p)
    assert reloaded.get("keep.pdf", "h") == OB
    assert reloaded.get("gone.pdf", "h") is None


def test_keys_are_platform_independent(tmp_path):
    """A cache written on Linux must resolve on Windows and vice versa.

    The cache is committed, so it crosses platforms by design. `str(Path)`
    yields "Disciplines/SWM/x.pdf" on POSIX and "Disciplines\\SWM\\x.pdf" on
    Windows, which would make every key miss on the other OS -- triggering a
    full reconversion and rewriting the whole 396KB file with the other
    separator on every platform switch.

    .ingestion_state.json already works around this by storing both spellings
    (26 backslash + 26 forward-slash keys for 28 files). Normalising once is
    cleaner than storing each key twice.
    """
    p = tmp_path / "ob.json"
    s = ObligationStore.load(p)
    s.put("Disciplines\\SWM\\ODF_SWM_Data_Dictionary.pdf", "h", OB)
    s.save()
    reloaded = ObligationStore.load(p)
    assert reloaded.get("Disciplines/SWM/ODF_SWM_Data_Dictionary.pdf", "h") == OB
    assert reloaded.get("Disciplines\\SWM\\ODF_SWM_Data_Dictionary.pdf", "h") == OB


def test_prune_matches_regardless_of_separator(tmp_path):
    p = tmp_path / "ob.json"
    s = ObligationStore.load(p)
    s.put("Disciplines/SWM/x.pdf", "h", OB)
    s.prune({"Disciplines\\SWM\\x.pdf"})
    assert s.get("Disciplines/SWM/x.pdf", "h") == OB


def test_prune_refuses_a_suspicious_shrink(tmp_path):
    """A scan that sees almost nothing must not empty the cache.

    The store is committed precisely so a checkout without a PDF converter
    still validates identically. An unconditional prune turned any transient
    scan failure into permanent silent data loss -- observed twice, most
    recently 28 entries -> 4 from an ordinary startup (found in a rules review).
    """
    from odf_validator.ingestion.obligation_store import ObligationStore
    store = ObligationStore(tmp_path / "c.json")
    for i in range(10):
        store.put(f"Disciplines/D{i}/dd.pdf", f"h{i}",
                  {("DT_RESULT", "Competition", "Gen"): "O"})

    dropped = store.prune({"Disciplines/D0/dd.pdf"})

    assert dropped == [], "a 90% shrink must be refused, not reported as drops"
    assert store.get("Disciplines/D9/dd.pdf", "h9") is not None, \
        "entries must survive a scan that lost almost everything"


def test_prune_still_drops_a_removed_discipline(tmp_path):
    """The prune's real purpose must keep working."""
    from odf_validator.ingestion.obligation_store import ObligationStore
    store = ObligationStore(tmp_path / "c.json")
    for i in range(10):
        store.put(f"Disciplines/D{i}/dd.pdf", f"h{i}",
                  {("DT_RESULT", "Competition", "Gen"): "O"})

    keep = {f"Disciplines/D{i}/dd.pdf" for i in range(10)} - {"Disciplines/D3/dd.pdf"}
    dropped = store.prune(keep)

    assert dropped == ["Disciplines/D3/dd.pdf"]
    assert store.get("Disciplines/D3/dd.pdf", "h3") is None


def test_prune_refuses_the_real_28_to_14_incident_shape(tmp_path):
    """The exact boundary that motivated the guard: a scan that sees precisely
    half of a real-sized (28-entry) committed cache. The old strict `<` let
    this through -- `14 < 14` is False -- silently deleting the other 14
    entries. This is the incident shape (28 -> 4 was the observed failure;
    exactly-half is the untested boundary next to it), not a synthetic one.
    """
    from odf_validator.ingestion.obligation_store import ObligationStore
    store = ObligationStore(tmp_path / "c.json")
    for i in range(28):
        store.put(f"Disciplines/D{i}/dd.pdf", f"h{i}",
                  {("DT_RESULT", "Competition", "Gen"): "O"})

    seen = {f"Disciplines/D{i}/dd.pdf" for i in range(14)}
    dropped = store.prune(seen)

    assert dropped == [], "a scan that saw exactly half of 28 must be refused"
    for i in range(28):
        assert store.get(f"Disciplines/D{i}/dd.pdf", f"h{i}") is not None, \
            f"entry {i} must survive a refused prune"


def test_prune_refuses_an_exact_half_shrink_on_a_small_cache(tmp_path):
    """Below 28, the same exact-half boundary must still refuse once the
    cache is large enough to be trusted as "real" (>= the small-cache
    exemption threshold)."""
    from odf_validator.ingestion.obligation_store import ObligationStore
    store = ObligationStore(tmp_path / "c.json")
    for i in range(4):
        store.put(f"Disciplines/D{i}/dd.pdf", f"h{i}",
                  {("DT_RESULT", "Competition", "Gen"): "O"})

    dropped = store.prune({"Disciplines/D0/dd.pdf", "Disciplines/D1/dd.pdf"})

    assert dropped == [], "a scan that saw exactly half of 4 must be refused"


def test_prune_still_drops_half_of_a_small_two_entry_cache(tmp_path):
    """The small-cache exemption: deleting one discipline from a two-DD pack
    is a real, legitimate operation (test_prune_forgets_dds_no_longer_in_the_pack
    is this same shape) and must keep pruning even though it is exactly half."""
    from odf_validator.ingestion.obligation_store import ObligationStore
    store = ObligationStore(tmp_path / "c.json")
    store.put("keep.pdf", "h", {("DT_RESULT", "Competition", "Gen"): "O"})
    store.put("gone.pdf", "h", {("DT_RESULT", "Competition", "Gen"): "O"})

    dropped = store.prune({"keep.pdf"})

    assert dropped == ["gone.pdf"]
    assert store.get("gone.pdf", "h") is None
    assert store.get("keep.pdf", "h") is not None


def test_prune_still_drops_below_the_small_cache_threshold(tmp_path):
    """A 3-entry cache is still below the small-cache exemption threshold (4),
    so a scan seeing 1 of 3 (well under half) must keep pruning normally."""
    from odf_validator.ingestion.obligation_store import ObligationStore
    store = ObligationStore(tmp_path / "c.json")
    store.put("keep.pdf", "h", {("DT_RESULT", "Competition", "Gen"): "O"})
    store.put("gone1.pdf", "h", {("DT_RESULT", "Competition", "Gen"): "O"})
    store.put("gone2.pdf", "h", {("DT_RESULT", "Competition", "Gen"): "O"})

    dropped = store.prune({"keep.pdf"})

    assert dropped == ["gone1.pdf", "gone2.pdf"]
    assert store.get("keep.pdf", "h") is not None


def test_prune_of_a_healthy_full_scan_prunes_and_reports_nothing(tmp_path):
    """A scan that sees everything must prune nothing and behave identically
    to before -- would_shrink stays 0, prune drops nothing."""
    from odf_validator.ingestion.obligation_store import ObligationStore
    store = ObligationStore(tmp_path / "c.json")
    for i in range(28):
        store.put(f"Disciplines/D{i}/dd.pdf", f"h{i}",
                  {("DT_RESULT", "Competition", "Gen"): "O"})

    seen = {f"Disciplines/D{i}/dd.pdf" for i in range(28)}

    assert store.would_shrink(seen) == 0
    assert store.prune(seen) == []
    for i in range(28):
        assert store.get(f"Disciplines/D{i}/dd.pdf", f"h{i}") is not None


def test_prune_of_an_empty_scan_is_refused(tmp_path):
    from odf_validator.ingestion.obligation_store import ObligationStore
    store = ObligationStore(tmp_path / "c.json")
    store.put("a.pdf", "h", {("DT_RESULT", "C", "Gen"): "O"})

    assert store.prune(set()) == []
    assert store.get("a.pdf", "h") is not None


def test_save_round_trips_correctly(tmp_path):
    import json
    from odf_validator.ingestion.obligation_store import ObligationStore
    path = tmp_path / "c.json"
    store = ObligationStore(path)
    store.put("a.pdf", "h", {("DT_RESULT", "C", "Gen"): "O"})
    store.save()

    assert json.loads(path.read_text(encoding="utf-8"))["a.pdf"]["hash"] == "h"
    assert not list(tmp_path.glob("*.tmp")), "the temp file must be renamed away"


def test_save_is_atomic(tmp_path, monkeypatch):
    """A failed rename must not leave a truncated cache behind.

    This must fail against the old `self.path.write_text(...)`
    implementation: that version writes the new (different) data directly
    into the destination file with no rename step at all, so the "original
    content survives" assertion below would fail. Asserting only "a file
    exists and no .tmp survives" (the previous version of this test) does
    not distinguish atomic-via-rename from truncate-in-place -- both satisfy
    it.
    """
    import os
    import json
    from odf_validator.ingestion.obligation_store import ObligationStore

    path = tmp_path / "c.json"
    good = {"a.pdf": {"hash": "h-good", "obligations": []}}
    path.write_text(json.dumps(good), encoding="utf-8")

    real_replace = os.replace

    def failing_replace(src, dst):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(os, "replace", failing_replace)

    store = ObligationStore(path)
    store.put("b.pdf", "h-new", {("DT_RESULT", "C", "Gen"): "O"})
    store.save()

    monkeypatch.setattr(os, "replace", real_replace)

    assert json.loads(path.read_text(encoding="utf-8")) == good, \
        "a failed rename must leave the original committed cache untouched"
    assert not list(tmp_path.glob("*.tmp")), \
        "a failed rename must not leave the temp file behind"
