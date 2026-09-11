"""Regression: routine semantic deduplication must not be reported as a
ruleset conflict.

SYOG26's 25 discipline rulesets each re-declare the same global GEN
code-membership checks verbatim, so a healthy load drops ~405 redundant
copies. Those drops are lossless housekeeping, not defects. Reporting them
on the same channel as genuine id collisions made the UI announce
"405 rule conflict(s) in this ruleset" for a pack with zero real problems.
"""
from pathlib import Path

from odf_validator.rules.loader import load_rule_defs

RULES_DIR = Path(__file__).resolve().parents[2] / "Rules"


def _rule_yaml(id_, applies_to, source):
    return (
        f"- id: {id_}\n  applies_to: {applies_to}\n  primitive: code_membership\n"
        f"  target: './/*[@RecordType]'\n  attribute: RecordType\n"
        f"  params: {{codeset: RECORD_TYPE}}\n  severity: warning\n  scope: message\n"
        f"  source_ref: {source}\n"
    )


def test_semantic_dedupe_is_reported_separately_from_conflicts(tmp_path):
    disc = tmp_path / "swm.yaml"
    disc.write_text(_rule_yaml("SWM_RECORDTYPE_CODE", "{disciplines: [SWM]}", "swm"),
                    encoding="utf-8")
    gen = tmp_path / "gen.yaml"
    gen.write_text(_rule_yaml("GEN_RECORDTYPE_CODE", "{}", "gen"), encoding="utf-8")

    rules, errors, conflicts, deduped, _spec = load_rule_defs([disc, gen])

    assert [r.id for r in rules] == ["GEN_RECORDTYPE_CODE"]
    assert errors == []
    # the drop is housekeeping -- it must NOT count as a conflict
    assert conflicts == []
    assert any("SWM_RECORDTYPE_CODE" in d and "GEN_RECORDTYPE_CODE" in d
               for d in deduped)


def test_id_collision_is_still_a_conflict(tmp_path):
    a = tmp_path / "a.yaml"
    a.write_text(_rule_yaml("DUP_RULE", "{}", "a"), encoding="utf-8")
    b = tmp_path / "b.yaml"
    b.write_text(_rule_yaml("DUP_RULE", "{}", "b"), encoding="utf-8")

    rules, errors, conflicts, deduped, _spec = load_rule_defs([a, b])

    assert len(rules) == 1
    assert len(conflicts) == 1 and "DUP_RULE" in conflicts[0]
    assert deduped == []


def test_syog26_loads_with_no_real_conflicts():
    """The user-visible symptom: SYOG26 reported 405 conflicts on a clean pack."""
    paths = sorted((RULES_DIR / "SYOG26").rglob("rules/*.yaml"))
    assert paths, "SYOG26 rule files not found"

    rules, errors, conflicts, deduped, _spec = load_rule_defs(paths)

    assert conflicts == [], f"unexpected real conflicts: {conflicts[:3]}"
    assert errors == []
    assert len(deduped) > 100, "expected the discipline/GEN duplicates to dedupe"
    assert rules, "pack must still load active rules"


def test_dedupe_never_drops_an_uncovered_rule():
    """Every dropped rule must have a surviving rule with identical semantics
    and an equal-or-broader scope -- otherwise dedupe silently loses a check."""
    import yaml
    from odf_validator.rules.loader import _semantic_key, _subsumes, _to_rule

    paths = sorted((RULES_DIR / "SYOG26").rglob("rules/*.yaml"))
    authored = []
    for p in paths:
        for d in yaml.safe_load(p.read_text(encoding="utf-8")) or []:
            authored.append(_to_rule(d))

    kept, _errors, _conflicts, _deduped, _spec = load_rule_defs(paths)
    kept_ids = {r.id for r in kept}

    orphaned = [
        r.id for r in authored
        if r.id not in kept_ids
        and not any(_semantic_key(k) == _semantic_key(r)
                    and _subsumes(k.applies_to, r.applies_to) for k in kept)
    ]
    assert orphaned == [], f"dedupe lost coverage for: {orphaned[:10]}"
