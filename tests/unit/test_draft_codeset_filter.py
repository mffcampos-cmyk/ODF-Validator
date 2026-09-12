"""A Data Dictionary line citing a codeset that does not exist must not become
a draft rule.

The load-time drop (see test_codeset_name_matching) makes such a rule
harmless, but it is a cure applied every startup to a wound reopened by every
import: the DD text is unchanged, so the next derivation offers the same dead
rule, approve-all activates it, and the banner reports it again. 17 rules were
in that loop after the 2026-09-11 import -- 13 SESSIONSTATUS copies citing
CC@SHEDULESTATUS (a typo in the documents, one letter short of
SCHEDULESTATUS) and 4 CLASS copies citing CC@DISCIPLINECLASS and
CC@DISCIPLINE_CLASS, for which the workbook has no table under any spelling.

Refusing at derivation ends the loop. The refusal is reported, not silent:
the operator should be able to see what the document asked for.
"""
from __future__ import annotations
from pathlib import Path
import yaml

from odf_validator.ingestion.builder import build_ruleset_pack

CODES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Codesets>
  <Codeset name="VENUE">
    <Code id="OLY" ENG_Description="Olympic Stadium"/>
  </Codeset>
  <Codeset name="SCHEDULESTATUS">
    <Code id="SCHEDULED" ENG_Description="Scheduled"/>
  </Codeset>
</Codesets>
"""

# The three lines below are the real shapes: one good codeset, one document
# typo, one codeset that simply does not exist for these Games.
DD_TEXT = ("Venue M CC@VENUE Venue where the session takes place\n"
           "Class O CC@DISCIPLINECLASS Code to identify the sport class\n"
           "SessionStatus M CC@SHEDULESTATUS Only use CANCELLED if applicable\n")


def _ruleset(tmp_path: Path, with_codes: bool = True) -> Path:
    root = tmp_path / "TESTSET"
    disc = root / "Disciplines" / "ATH"
    disc.mkdir(parents=True)
    (disc / "ODF_ATH_Data_Dictionary.md").write_text(DD_TEXT, encoding="utf-8")
    if with_codes:
        (root / "codes").mkdir()
        (root / "codes" / "codes.xml").write_text(CODES_XML, encoding="utf-8")
    (root / "pack.yaml").write_text('version: "test"\n', encoding="utf-8")
    return root


def _drafts(root: Path) -> list[dict]:
    f = (root / "Disciplines" / "ATH" / ".drafts"
         / "ODF_ATH_Data_Dictionary.md.draft.yaml")
    if not f.exists():
        return []
    return yaml.safe_load(f.read_text(encoding="utf-8")) or []


def test_only_the_resolvable_codeset_becomes_a_draft(tmp_path):
    root = _ruleset(tmp_path)

    build_ruleset_pack(root)

    ids = {d["id"] for d in _drafts(root)}
    assert "ATH_VENUE_CODE" in ids
    assert "ATH_CLASS_CODE" not in ids, (
        "the workbook has no class table under any spelling, so this rule "
        "could only ever be approved and then dropped")
    assert "ATH_SESSIONSTATUS_CODE" not in ids, (
        "CC@SHEDULESTATUS is a typo in the document; the GEN rule covers "
        "@SessionStatus correctly")


def test_the_refusal_is_reported_with_the_document_line(tmp_path):
    root = _ruleset(tmp_path)

    pack = build_ruleset_pack(root)

    notes = pack.report.unmatched_codesets
    assert len(notes) == 2, notes
    joined = " | ".join(notes)
    assert "DISCIPLINECLASS" in joined and "SHEDULESTATUS" in joined
    assert "ODF_ATH_Data_Dictionary.md" in joined, (
        "the note must name the document, so the operator can go and read "
        "the line that asked for it")
    assert not [e for e in pack.report.errors if "DISCIPLINECLASS" in e], (
        "a refused draft is not a rule that failed to load; keeping it off "
        "`errors` is the same reasoning as dd_unconvertible")


def test_a_pack_with_no_code_tables_still_offers_every_draft(tmp_path):
    """Same guard as the loader's: with no workbook loaded, an unknown name
    says nothing about the rule, and refusing to derive would hide the DD's
    content from the reviewer for a reason that has nothing to do with it."""
    root = _ruleset(tmp_path, with_codes=False)

    pack = build_ruleset_pack(root)

    ids = {d["id"] for d in _drafts(root)}
    assert ids == {"ATH_VENUE_CODE", "ATH_CLASS_CODE",
                   "ATH_SESSIONSTATUS_CODE"}
    assert pack.report.unmatched_codesets == []


# The channel has to reach the operator, or "reported" means "written to a
# dataclass nobody reads". app.js draws the pack-report strip off /packs, and
# tests/js/error_states.test.js exercises that path against a DOM stub.

def test_the_channel_is_exposed_by_the_packs_endpoint(tmp_path, monkeypatch):
    import api.app as app_module
    from fastapi.testclient import TestClient

    rules_root = tmp_path / "Rules"
    root = _ruleset(rules_root / "_placeholder")   # build under Rules/TESTSET
    monkeypatch.setattr(app_module, "RULES_ROOT", root.parent)
    monkeypatch.setattr(app_module, "PACKS", {})
    app_module.discover_packs()

    row = next(p for p in TestClient(app_module.app).get("/packs").json()
               if p["name"] == "TESTSET")

    assert "unmatched_codesets" in row, sorted(row)
    assert len(row["unmatched_codesets"]) == 2, row["unmatched_codesets"]
