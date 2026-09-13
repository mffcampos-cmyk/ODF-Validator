"""A ruleset awaiting its Common Codes workbook has not failed to load rules.

A fresh clone of the public repository ships the authored rules and none of
the IOC documents -- the publication filter withholds every .pdf, .xlsx and
.xsd, and the app fetches them on first launch. So on first start there is no
codes workbook, every code_membership rule is inert, and the banner read:

    54 rule(s) failed to load - first: pack.yaml root_xsd 'odf2.xsd' not
    found; falling back to heuristic.
    89 rules active - 403 duplicate discipline rules merged - 2 generic
    rules superseded by discipline rules

Fifty-three of those 54 came from the missing workbook: one summary line and
one line per affected rule. Nothing failed to load -- 89 rules are active and
the count says so in the same breath. And 52 lines that differ only by rule
id are not 52 findings: they have one cause and one remedy between them.

The per-rule detail stays where it earns its place -- a pack that HAS code
tables and a rule naming a codeset those tables do not provide is a real,
rule-specific mismatch that a human has to look at. `test_the_per_rule_...`
below pins that half so this does not become silence.
"""
from __future__ import annotations
from pathlib import Path

from odf_validator.ingestion.builder import build_ruleset_pack

CODE_RULE = """\
- id: {id}
  applies_to: {{}}
  primitive: code_membership
  target: './/*[@{attr}]'
  attribute: {attr}
  params: {{codeset: {codeset}}}
  severity: error
  scope: message
  source_ref: 'hand-authored, test fixture'
"""


def _pack(tmp_path: Path, name: str, rules: str) -> Path:
    d = tmp_path / name
    (d / "rules").mkdir(parents=True)
    (d / "pack.yaml").write_text("version: '2026.09'\n", encoding="utf-8")
    (d / "rules" / "codes.yaml").write_text(rules, encoding="utf-8")
    return d


def _three_code_rules(tmp_path: Path, name: str) -> Path:
    return _pack(tmp_path, name, "".join(
        CODE_RULE.format(id=f"GEN_{c}_CODE", attr=c.title(), codeset=c)
        for c in ("VENUE", "COUNTRY", "PHASE")))


def test_a_pack_with_no_code_tables_is_not_a_rule_load_failure(tmp_path):
    pack = build_ruleset_pack(_three_code_rules(tmp_path, "FRESHCLONE"))

    assert len(pack.rules) == 3, "the rules load; they simply cannot fire"
    assert pack.report.errors == [], pack.report.errors
    assert pack.report.codes_unavailable, (
        "and silence is the other failure mode -- rules that cannot fire "
        "while nothing on screen says so is how @Class went unnoticed")


def test_the_missing_workbook_is_one_note_not_one_per_rule(tmp_path):
    """52 lines differing only by rule id are one condition, not 52
    findings: with no tables at all, every code_membership rule is affected
    without exception, so the set is derivable and the count is the useful
    part. `deduped` and `specialised` already report bulk facts this way."""
    pack = build_ruleset_pack(_three_code_rules(tmp_path, "ONELINE"))

    assert len(pack.report.codes_unavailable) == 1, pack.report.codes_unavailable
    note = pack.report.codes_unavailable[0]
    assert "3" in note, f"the note has to carry the count: {note}"
    assert "GEN_VENUE_CODE" not in note, "not an enumeration in disguise"


def test_a_pack_with_no_code_rules_says_nothing(tmp_path):
    """No workbook and nothing that wanted one is not a finding at all."""
    d = tmp_path / "NOCODERULES"
    (d / "rules").mkdir(parents=True)
    (d / "pack.yaml").write_text("version: ''\n", encoding="utf-8")
    (d / "rules" / "plain.yaml").write_text(
        "- id: GEN_ITEMNUM\n"
        "  applies_to: {}\n"
        "  primitive: value_format\n"
        "  target: './/*[@ItemNum]'\n"
        "  attribute: ItemNum\n"
        "  params: {regex: '^[0-9]+$'}\n"
        "  severity: error\n"
        "  scope: message\n"
        "  source_ref: 'hand-authored, test fixture'\n", encoding="utf-8")

    pack = build_ruleset_pack(d)

    assert pack.report.codes_unavailable == []
    assert pack.report.errors == []


def test_the_per_rule_naming_survives_when_tables_do_exist(tmp_path):
    """The half that is NOT collapsed. With code tables present, a rule
    naming a codeset they do not provide is a rule-specific mismatch -- one
    rule wrong among many right -- and the operator needs its id. That case
    also drops the rule, so it stays on `errors` where a rule that did not
    survive the load belongs."""
    d = _pack(tmp_path, "HASTABLES",
              CODE_RULE.format(id="GEN_NOSUCH_CODE", attr="Nope",
                               codeset="NOSUCHTABLE"))
    (d / "codes").mkdir()
    (d / "codes" / "codes.xml").write_text(
        '<?xml version="1.0"?>\n'
        '<CommonCodes><Codeset name="VENUE">'
        '<Code id="OLY" ENG_Description="Olympic Stadium"/>'
        '</Codeset></CommonCodes>', encoding="utf-8")

    pack = build_ruleset_pack(d)

    assert pack.codes.names(), "fixture must actually load a table"
    assert any("GEN_NOSUCH_CODE" in e for e in pack.report.errors), \
        pack.report.errors
    assert pack.report.codes_unavailable == [], (
        "this pack has code tables; the missing-workbook note must not fire")
