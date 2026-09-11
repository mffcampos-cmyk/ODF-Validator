"""A degraded obligation cache must reach the alarm strip.

Silent degradation is the failure mode this subsystem keeps producing: the
cache emptied, /packs still said errors: 0, /rulesets still listed every
discipline, and the only note on screen said "rules unaffected" -- which is
the opposite of true, because losing a DD un-suppresses XSD errors across
every message for that discipline. Findings F-H3/F-H4.
"""
from pathlib import Path

from odf_validator.ingestion.builder import build_ruleset_pack
from odf_validator.ingestion.obligation_store import STORE_FILE_NAME, ObligationStore


def _ruleset_with_a_stale_cache_entry(tmp_path: Path) -> Path:
    ruleset = tmp_path / "TESTSET"
    disc = ruleset / "Disciplines" / "ARC"
    disc.mkdir(parents=True)
    (disc / "ARC_DD.md").write_text(
        "Venue M CC@VENUE Venue where the session takes place\n", encoding="utf-8")
    # Three entries for DDs that no longer exist on disk. ObligationStore.prune()
    # only refuses (rather than silently pruning) once the cache holds at
    # least SMALL_CACHE_EXEMPTION (4) entries and the scan accounts for at
    # most MIN_KEEP_FRACTION (0.5) of them; below that entry count the guard
    # is deliberately exempt, since "half" and "a third" of a handful of DDs
    # are not distinguishable from a real, small, legitimate deletion. This
    # run also caches ARC_DD.md for the first time, so the store holds 4 keys
    # total (3 stale + freshly-put ARC) by the time prune() runs -- at the
    # exemption threshold, with the scan accounting for only 1/4. That
    # reproduces the real 2026-08-26 incident (a cache mostly
    # unaccounted-for), which is what this test exists to catch.
    store = ObligationStore(ruleset / STORE_FILE_NAME)
    store.put("Disciplines/GONE/GONE_DD.pdf", "h",
              {("DT_RESULT", "Competition", "Gen"): "O"})
    store.put("Disciplines/ALSOGONE/ALSOGONE_DD.pdf", "h",
              {("DT_RESULT", "Competition", "Gen"): "O"})
    store.put("Disciplines/STILLGONE/STILLGONE_DD.pdf", "h",
              {("DT_RESULT", "Competition", "Gen"): "O"})
    store.save()
    return ruleset


def test_a_cache_the_scan_cannot_account_for_is_reported(tmp_path):
    ruleset = _ruleset_with_a_stale_cache_entry(tmp_path)

    pack = build_ruleset_pack(ruleset)

    assert any("obligation" in e.lower() for e in pack.report.cache_warnings), (
        "a cache entry the scan did not see must be reported, not resolved "
        f"in silence; got cache_warnings={pack.report.cache_warnings}")


def test_a_cache_integrity_problem_is_not_a_rule_load_failure(tmp_path):
    # `errors` is rendered by the UI as "N rule(s) failed to load". No rule
    # failed to load here -- the cache was left intact, unpruned. Final
    # whole-branch review, cache-integrity mislabelling.
    ruleset = _ruleset_with_a_stale_cache_entry(tmp_path)

    pack = build_ruleset_pack(ruleset)

    assert not [e for e in pack.report.errors if "obligation cache" in e.lower()], (
        f"a cache-integrity warning must not land in `errors`; got {pack.report.errors}")


def test_cache_warning_remedy_names_the_actionable_fix(tmp_path):
    # The old remedy ("check the Rules folder is fully readable, then
    # restart") cannot resolve a permanently-stale cache (all its DDs
    # renamed): rereading and restarting reproduces the exact same mismatch
    # forever. The only fix is to delete the cache file and rebuild it.
    ruleset = _ruleset_with_a_stale_cache_entry(tmp_path)

    pack = build_ruleset_pack(ruleset)

    warning = pack.report.cache_warnings[0]
    assert ".dd_obligations.json" in warning, warning
    assert "restart" not in warning.lower(), (
        f"remedy still points at a restart, which cannot fix a permanently "
        f"stale cache: {warning}")


def test_a_healthy_pack_reports_nothing_about_obligations(tmp_path):
    ruleset = tmp_path / "CLEAN"
    disc = ruleset / "Disciplines" / "ARC"
    disc.mkdir(parents=True)
    (disc / "ARC_DD.md").write_text(
        "Venue M CC@VENUE Venue where the session takes place\n", encoding="utf-8")

    pack = build_ruleset_pack(ruleset)

    assert not [e for e in pack.report.errors if "obligation" in e.lower()], (
        f"a healthy pack must stay quiet; got {pack.report.errors}")
    assert not pack.report.cache_warnings, (
        f"a healthy pack must stay quiet; got {pack.report.cache_warnings}")
