from pathlib import Path
from odf_validator.ingestion.builder import build_ruleset_pack
from odf_validator.pipeline.orchestrator import Pipeline
from tests.conftest import needs_populated_ruleset

PACK = build_ruleset_pack(Path("Rules/SYOG26"))
GOOD = b'<OdfBody CompetitionCode="SYOG2026" DocumentCode="ARC" DocumentType="DT_RESULT" Version="1" Date="d" Time="t" LogicalDate="d" FeedFlag="P" Source="S"><Competition><Discipline Code="ARC-------------------------------"/></Competition></OdfBody>'


def test_run_populates_metadata_and_runs_layers():
    res = Pipeline().run(GOOD, PACK)
    assert res.doc_type == "DT_RESULT"
    # The message now carries a 34-char RSC; dispatch normalises it, so the
    # pipeline result still reports the three-letter discipline.
    assert res.discipline == "ARC"
    assert res.pack_name == "SYOG26"


def test_malformed_short_circuits():
    res = Pipeline().run(b"<bad", PACK)
    assert res.doc_type is None
    assert any(f.layer.value == "structural" for f in res.findings)


def test_core_rules_run_for_every_pack():
    # GOOD message with an empty optional attribute: only the engine-bundled
    # core rule can flag it if the pack carries no generic rules.
    xml = GOOD.replace(b'Source="S"', b'Source="S" Organisation=""')
    res = Pipeline().run(xml, PACK)
    assert any(f.rule_id == "CORE_NO_EMPTY_ATTRS" for f in res.findings)


def test_core_rules_run_before_pack_rules():
    xml = GOOD.replace(b'Source="S"', b'Source="S" Organisation=""')
    res = Pipeline().run(xml, PACK)
    non_structural = [f for f in res.findings if f.layer.value != "structural"]
    core_idx = [i for i, f in enumerate(non_structural)
                if f.rule_id.startswith("CORE_")]
    pack_idx = [i for i, f in enumerate(non_structural)
                if not f.rule_id.startswith("CORE_") and f.rule_id != "RULE_CRASH"]
    assert core_idx and (not pack_idx or max(core_idx) < min(pack_idx))


@needs_populated_ruleset
def test_codevalue_equivalence_bad_discipline_code():
    # Previously CODE_MAPPINGS flagged an unknown Discipline code at Layer.CODE.
    # The migrated CORE_DISCIPLINE_CODE rule must preserve that behavior.
    # GOOD now carries the full 34-char RSC, so the replace target must match
    # it in full -- a bare 'Discipline Code="ARC"' substring no longer exists
    # in GOOD and would silently no-op, leaving "bad" identical to GOOD.
    bad = GOOD.replace(b'Discipline Code="ARC-------------------------------"',
                        b'Discipline Code="ZZZ"')
    res = Pipeline().run(bad, PACK)
    hits = [f for f in res.findings
            if f.rule_id == "CORE_DISCIPLINE_CODE" and f.layer.value == "code"]
    assert len(hits) == 1
