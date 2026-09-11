from pathlib import Path
from odf_validator.ingestion.scanner import scan_ruleset


def _make_ruleset(tmp_path: Path) -> Path:
    root = tmp_path / "SYOG26"
    (root / "xsd").mkdir(parents=True)
    (root / "xsd" / "odf2.xsd").write_text("<xsd/>")
    (root / "codes").mkdir()
    (root / "codes" / "codes.xlsx").write_bytes(b"stub")
    (root / "GEN.md").write_text("gen doc")
    disc = root / "Disciplines" / "ARC"
    disc.mkdir(parents=True)
    (disc / "ARC_DD.md").write_text("arc dd")
    # app-managed dirs must be skipped even though they contain .yaml/.md
    (root / "rules").mkdir()
    (root / "rules" / "gen_common.yaml").write_text("[]")
    (disc / "rules").mkdir()
    (disc / "rules" / "config.yaml").write_text("[]")
    (disc / ".drafts").mkdir()
    (disc / ".drafts" / "ARC_DD.md.draft.yaml").write_text("[]")
    (root / ".ingestion_state.json").write_text("{}")
    (root / "notes.txt").write_text("not recognized")
    return root


def test_scan_types_every_source_file(tmp_path):
    root = _make_ruleset(tmp_path)
    result = scan_ruleset(root)

    assert [p.name for p in result.xsd_files] == ["odf2.xsd"]
    assert [p.name for p in result.code_files] == ["codes.xlsx"]
    assert [p.name for p in result.unknown_files] == ["notes.txt"]


def test_scan_tags_dd_files_with_their_discipline(tmp_path):
    root = _make_ruleset(tmp_path)
    result = scan_ruleset(root)

    by_name = {p.name: disc for p, disc in result.dd_files}
    assert by_name["GEN.md"] is None          # ruleset-level, not under Disciplines/
    assert by_name["ARC_DD.md"] == "ARC"


def test_scan_skips_app_managed_rules_and_drafts_dirs(tmp_path):
    root = _make_ruleset(tmp_path)
    result = scan_ruleset(root)

    all_files = (result.xsd_files + result.code_files
                 + [p for p, _ in result.dd_files] + result.unknown_files)
    names = {p.name for p in all_files}
    assert "gen_common.yaml" not in names
    assert "config.yaml" not in names
    assert "ARC_DD.md.draft.yaml" not in names
    assert ".ingestion_state.json" not in names


def test_scan_skips_reference_dir(tmp_path):
    # _reference/ holds human-facing reference material (e.g. a consolidated
    # rules JSON dump, a reference markdown doc). It must never be swept into
    # ingestion: an unrecognized extension there would surface as a spurious
    # "Unrecognized file, skipped" load error, and a .md there would be
    # misclassified as a Data Dictionary and run through draft extraction.
    root = tmp_path / "SYOG26"
    ref = root / "_reference"
    ref.mkdir(parents=True)
    (ref / "odf_rules_consolidated.json").write_text("{}")
    (ref / "ODF_Validation_Rules_Reference.md").write_text("# ref doc")

    result = scan_ruleset(root)

    assert result.unknown_files == []
    assert result.dd_files == []


def test_dd_file_directly_in_disciplines_dir_has_no_discipline(tmp_path):
    root = tmp_path / "SYOG26"
    disciplines = root / "Disciplines"
    disciplines.mkdir(parents=True)
    (disciplines / "stray.md").write_text("not under a discipline subfolder")
    result = scan_ruleset(root)
    by_name = {p.name: disc for p, disc in result.dd_files}
    assert by_name["stray.md"] is None
