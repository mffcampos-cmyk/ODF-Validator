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


# ------------------------------------------------------- app state files ---
#
# The scanner used to name the app's own state files one by one
# (.ingestion_state.json, .dd_obligations.json). The sync feature then added a
# third, .sources.json, and nobody came back here -- so the first import
# greeted the operator with "30 rule(s) failed to load -- first: Unrecognized
# file, skipped: .sources.json". Every one of these files is a dotfile, and no
# IOC source document ever is, so the rule is the leading dot rather than a
# list that has to be maintained in two places.

def test_the_source_provenance_file_is_not_a_source_document(tmp_path):
    root = tmp_path / "SYOG26"
    root.mkdir()
    (root / ".sources.json").write_text('{"entries": {}}', encoding="utf-8")

    scan = scan_ruleset(root)

    assert scan.unknown_files == [], (
        ".sources.json is written by the app itself; typing it as an "
        "unrecognised source document is what produced the load error")


def test_any_app_dotfile_is_skipped_not_just_the_ones_named_today(tmp_path):
    """The next state file the app invents must not reopen this bug."""
    root = tmp_path / "SYOG26"
    (root / "Disciplines" / "ARC").mkdir(parents=True)
    for name in (".ingestion_state.json", ".dd_obligations.json",
                 ".sources.json", ".some_future_cache.json"):
        (root / name).write_text("{}", encoding="utf-8")
    (root / "Disciplines" / "ARC" / ".per_discipline_state.json").write_text(
        "{}", encoding="utf-8")

    scan = scan_ruleset(root)

    assert scan.unknown_files == []
    assert scan.dd_files == []
    assert scan.code_files == []
