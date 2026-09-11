from pathlib import Path
import shutil
from odf_validator.ingestion.builder import build_ruleset_pack
from tests.conftest import needs_populated_ruleset

pytestmark = needs_populated_ruleset

REAL_XSD_DIR = Path("Rules/SYOG26/xsd")
def _codes_xlsx() -> Path:
    """The pack's Common Codes workbook, whatever version is installed.

    Pinning the filename broke every test here when the pack moved from
    v1.9.1 to v2.1 (2026-09-01). The version is the pack's business, not the
    test's.
    """
    found = sorted(Path("Rules/SYOG26/codes").glob("*.xlsx"))
    assert len(found) == 1, f"expected exactly one codes workbook, found {found}"
    return found[0]


def _make_ruleset(tmp_path: Path) -> Path:
    # The workbook is located here, per test, rather than at import time, so
    # that collecting this module cannot fail when it has not been downloaded.
    real_codes = _codes_xlsx()
    root = tmp_path / "SYOG26"
    xsd_dir = root / "xsd"
    xsd_dir.mkdir(parents=True)
    for f in REAL_XSD_DIR.glob("*.xsd"):
        shutil.copy(f, xsd_dir / f.name)
    codes_dir = root / "codes"
    codes_dir.mkdir()
    shutil.copy(real_codes, codes_dir / real_codes.name)

    disc = root / "Disciplines" / "ARC"
    disc.mkdir(parents=True)
    (disc / "ARC_DD.md").write_text(
        "Venue M CC@VENUE Venue where the session takes place\n")
    (root / "rules").mkdir()
    (root / "rules" / "gen_common.yaml").write_text(
        "- id: GEN_MANUAL\n"
        "  applies_to: {}\n"
        "  primitive: value_format\n"
        "  target: './/*[@ItemNum]'\n"
        "  attribute: ItemNum\n"
        "  params: {regex: '^[0-9]+$'}\n"
        "  severity: error\n"
        "  scope: message\n"
        "  source_ref: 'hand-authored, grandfathered'\n"
    )
    return root


def test_builds_a_working_pack_with_schema_codes_and_rules(tmp_path):
    root = _make_ruleset(tmp_path)
    pack = build_ruleset_pack(root)

    assert pack.name == "SYOG26"
    assert pack.report.errors == []
    assert pack.schema is not None
    assert pack.codes.table("COUNTRY") is not None
    assert pack.disciplines == ["ARC"]
    assert {r.id for r in pack.rules} == {"GEN_MANUAL"}


def test_new_dd_file_produces_a_draft_not_an_active_rule(tmp_path):
    root = _make_ruleset(tmp_path)
    pack = build_ruleset_pack(root)

    # The DD's code_membership rule must NOT be active yet (unapproved draft).
    assert "ARC_VENUE_CODE" not in {r.id for r in pack.rules}
    draft_file = root / "Disciplines" / "ARC" / ".drafts" / "ARC_DD.md.draft.yaml"
    assert draft_file.exists()


def test_unchanged_dd_file_is_not_reprocessed_on_second_build(tmp_path):
    root = _make_ruleset(tmp_path)
    build_ruleset_pack(root)
    draft_file = root / "Disciplines" / "ARC" / ".drafts" / "ARC_DD.md.draft.yaml"
    first_mtime = draft_file.stat().st_mtime_ns

    build_ruleset_pack(root)   # second build, DD file untouched
    assert draft_file.stat().st_mtime_ns == first_mtime


def test_approved_draft_becomes_an_active_rule_on_next_build(tmp_path):
    from odf_validator.ingestion import draft_store

    root = _make_ruleset(tmp_path)
    build_ruleset_pack(root)
    draft_file = root / "Disciplines" / "ARC" / ".drafts" / "ARC_DD.md.draft.yaml"
    draft_store.approve_draft(draft_file, "ARC_VENUE_CODE")

    pack = build_ruleset_pack(root)
    assert "ARC_VENUE_CODE" in {r.id for r in pack.rules}


def test_unrecognized_file_is_reported_not_silently_dropped(tmp_path):
    root = _make_ruleset(tmp_path)
    (root / "notes.txt").write_text("what is this")
    pack = build_ruleset_pack(root)
    assert any("notes.txt" in e for e in pack.report.errors)


def test_dd_conversion_failure_is_recorded_and_not_marked_processed(tmp_path):
    class _BoomConverter:
        def convert(self, path):
            raise ValueError("simulated conversion failure")

    root = _make_ruleset(tmp_path)
    pack = build_ruleset_pack(root, converter=_BoomConverter())

    # .md passes through without touching the converter, so force a .pdf too.
    disc = root / "Disciplines" / "ARC"
    (disc / "ARC_DD.pdf").write_bytes(b"%PDF-1.4 stub")
    pack = build_ruleset_pack(root, converter=_BoomConverter())

    # Recorded in dd_unconvertible, and NOT in report.errors. Both halves
    # matter. report.errors is rendered by web/app.js as "N rule(s) failed to
    # load", so a conversion failure appearing there tells the operator their
    # authored rules are broken when what actually happened is that one source
    # document could not be read -- a different problem with a different fix.
    # Separating the channels is the whole reason dd_unconvertible exists.
    #
    # The second assertion is the load-bearing one: this test previously
    # required the message to be in report.errors, and so pinned the
    # mislabelling in place. It passed while builder.py converted the failed
    # document a second time (guaranteed to fail again) purely to log it to the
    # wrong channel.
    assert any("ARC_DD.pdf" in e for e in pack.report.dd_unconvertible)
    assert not any("ARC_DD.pdf" in e for e in pack.report.errors)
    draft_file = disc / ".drafts" / "ARC_DD.pdf.draft.yaml"
    assert not draft_file.exists()

    # Failure must not be marked processed: state stays absent for this file,
    # so the next startup retries it instead of silently giving up forever.
    import json
    state = json.loads((root / ".ingestion_state.json").read_text(encoding="utf-8"))
    assert str((disc / "ARC_DD.pdf").relative_to(root)) not in state


def test_manifest_sets_version_and_root_xsd(tmp_path):
    d = tmp_path / "TESTPACK"
    d.mkdir()
    (d / "a.xsd").write_text(
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
        '<xs:element name="A"/></xs:schema>', encoding="utf-8")
    (d / "b.xsd").write_text(
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
        '<xs:element name="B"/></xs:schema>', encoding="utf-8")
    (d / "pack.yaml").write_text("version: '2.1'\nroot_xsd: b.xsd\n",
                                 encoding="utf-8")
    pack = build_ruleset_pack(d)
    assert pack.version == "2.1"
    assert pack.root_xsd.name == "b.xsd"
    assert not any("pack.yaml" in e for e in pack.report.errors)


def test_no_manifest_keeps_heuristics(tmp_path):
    d = tmp_path / "TESTPACK2"
    d.mkdir()
    (d / "odf2.xsd").write_text(
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
        '<xs:element name="A"/></xs:schema>', encoding="utf-8")
    pack = build_ruleset_pack(d)
    assert pack.version == ""
    assert pack.root_xsd.name == "odf2.xsd"
