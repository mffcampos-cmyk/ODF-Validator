"""A rule resting on self-contradictory documentation reports, it does not fail.

Owner decision, 2026-09-01. The Data Dictionaries contradict themselves in
several places — a machine-readable column saying one thing and the prose
beside it another, or a blanket "N/A" that a later row overrides. Where a rule
is derived from such a row, the honest severity is `warning`: the finding is
worth surfacing, but the documentation does not support failing a message on
it.

The asymmetry is the point. A wrong warning costs a line in a report. A wrong
error at scale is what this project has repeatedly paid for — 5,902 findings
from one ambiguous element name, 567 from one flat-read attribute table.
"""
from pathlib import Path

import pytest
import yaml

RULES_ROOT = Path(__file__).resolve().parents[2] / "Rules" / "SYOG26"

# Rules whose basis the DD itself undermines. Each must stay a warning, and
# each must say why in its own source_ref.
CONTRADICTED = {
    "ATH_POS_POSINT": "disputed",
    "GAR_POS_POSINT": "disputed",
    "ARC_DOCSUBCODE_ABSENT": "contradicts itself",
}


def _all_rules():
    for path in sorted(RULES_ROOT.glob("**/rules/*.yaml")):
        for entry in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
            yield path, entry


@pytest.mark.parametrize("rule_id", sorted(CONTRADICTED))
def test_contradicted_rules_warn_rather_than_error(rule_id):
    found = [e for _, e in _all_rules() if e["id"] == rule_id]

    assert found, f"{rule_id} not found"
    for entry in found:
        assert entry["severity"] == "warning", (
            f"{rule_id} rests on documentation that contradicts itself; "
            "it must not fail a message")


@pytest.mark.parametrize("rule_id,marker", sorted(CONTRADICTED.items()))
def test_the_downgrade_records_its_reason(rule_id, marker):
    """A severity that looks arbitrary invites someone to 'restore' it."""
    found = [e for _, e in _all_rules() if e["id"] == rule_id]

    for entry in found:
        ref = entry["source_ref"]
        assert marker in ref, f"{rule_id}: source_ref does not explain the downgrade"
        assert "error -> warning" in ref or "error → warning" in ref


def test_the_pos_rules_are_still_provisional():
    """Their scope was narrowed on disputed evidence; that must stay visible."""
    for rule_id in ("ATH_POS_POSINT", "GAR_POS_POSINT"):
        entry = next(e for _, e in _all_rules() if e["id"] == rule_id)
        assert "PROVISIONAL" in entry["source_ref"]


def test_no_error_rule_silently_rests_on_a_contradiction():
    """Catches the next one: an error-severity rule that admits a DD problem.

    If a rule's own source_ref says the documentation is disputed or
    self-contradictory, it should not be failing messages. New rules that
    describe such a conflict must either be downgraded or added to
    CONTRADICTED with a deliberate justification.
    """
    suspicious = []
    for _, entry in _all_rules():
        if entry.get("severity") != "error":
            continue
        ref = (entry.get("source_ref") or "").lower()
        if any(k in ref for k in ("contradicts itself", "disputed", "provisional")):
            suspicious.append(entry["id"])

    assert suspicious == [], (
        "these rules fail messages on documentation they themselves describe "
        f"as unreliable: {sorted(set(suspicious))}")
