"""Two primitives the engine lacked: sibling order and date-pair order.

Every SYOG26 discipline DD carries a Message Sort section ("The message is
sorted by Team @Code", GEN 2.1.3.6), and no primitive checked it -- the
CORE_SORTORDER_* rules check @SortOrder's value shape, not the order of
anything. And a Session whose EndDate precedes its StartDate is stated
nowhere, which is why datetime_order is a hand-written pack rule rather than
a drafted one.
"""
from pathlib import Path

from lxml import etree

from odf_validator.ingestion.builder import build_ruleset_pack
from odf_validator.pipeline.orchestrator import Pipeline
from odf_validator.rules.defs_model import RuleDef, AppliesTo
from odf_validator.rules.primitives import PRIMITIVES
from odf_validator.model import Severity, Scope
from tests.conftest import needs_populated_ruleset


def rule(primitive, target, params, attribute=None):
    return RuleDef("R", AppliesTo([], [], []), primitive, target, attribute,
                   params, Severity.ERROR, Scope.MESSAGE, "src")


def run(primitive, xml, params, target=".//Competition"):
    return PRIMITIVES[primitive](etree.fromstring(xml), rule(primitive, target, params), None, None)


def teams(*codes):
    return "<OdfBody><Competition>" + "".join(f'<Team Code="{c}"/>' for c in codes) + "</Competition></OdfBody>"


# --- sort_order ----------------------------------------------------------

def test_sorted_siblings_pass():
    assert run("sort_order", teams("ARC", "ATH", "BKG"), {"child": "Team", "by": ["Code"]}) == []


def test_out_of_order_sibling_is_reported_once_at_the_offender():
    out = run("sort_order", teams("ARC", "BKG", "ATH"), {"child": "Team", "by": ["Code"]})
    assert len(out) == 1
    assert "ATH" in out[0].message and "BKG" in out[0].message
    assert out[0].location.path.endswith("/Team[3]")


def test_lexical_is_the_default_comparison():
    """Lexically '10' < '2'; that is the order this rule demands unless told
    otherwise, and the reason @SortOrder rules must say compare: numeric."""
    assert run("sort_order", teams("10", "2"), {"child": "Team", "by": ["Code"]}) == []
    assert len(run("sort_order", teams("2", "10"), {"child": "Team", "by": ["Code"]})) == 1


def test_numeric_comparison():
    p = {"child": "Team", "by": ["Code"], "compare": "numeric"}
    assert run("sort_order", teams("2", "10"), p) == []
    assert len(run("sort_order", teams("10", "2"), p)) == 1


def test_a_non_numeric_value_under_numeric_comparison_is_skipped_not_reported():
    """Value shape is another rule's job."""
    p = {"child": "Team", "by": ["Code"], "compare": "numeric"}
    assert run("sort_order", teams("1", "x", "3"), p) == []


def test_multiple_keys_compare_in_order():
    xml = ('<OdfBody><Competition>'
           '<Result Rank="1" SortOrder="2"/><Result Rank="1" SortOrder="1"/>'
           '</Competition></OdfBody>')
    p = {"child": "Result", "by": ["Rank", "SortOrder"], "compare": "numeric"}
    assert len(run("sort_order", xml, p)) == 1
    assert run("sort_order", xml, {"child": "Result", "by": ["Rank"], "compare": "numeric"}) == []


def test_siblings_missing_the_key_are_skipped():
    xml = '<OdfBody><Competition><Team Code="B"/><Team/><Team Code="A"/></Competition></OdfBody>'
    out = run("sort_order", xml, {"child": "Team", "by": ["Code"]})
    assert len(out) == 1 and out[0].location.path.endswith("/Team[3]")


def test_only_the_named_child_tag_is_compared():
    xml = '<OdfBody><Competition><Team Code="B"/><Other Code="A"/><Team Code="C"/></Competition></OdfBody>'
    assert run("sort_order", xml, {"child": "Team", "by": ["Code"]}) == []


def test_descending_order_can_be_demanded():
    p = {"child": "Team", "by": ["Code"], "descending": True}
    assert run("sort_order", teams("C", "B", "A"), p) == []
    assert len(run("sort_order", teams("A", "B"), p)) == 1


def test_each_parent_is_checked_independently():
    xml = ('<OdfBody><Competition><Result><Athlete Code="B"/><Athlete Code="A"/></Result>'
           '<Result><Athlete Code="A"/><Athlete Code="B"/></Result></Competition></OdfBody>')
    out = run("sort_order", xml, {"child": "Athlete", "by": ["Code"]}, target=".//Result")
    assert len(out) == 1 and "/Result[1]/" in out[0].location.path


# --- datetime_order ------------------------------------------------------

def session(start, end):
    return f'<OdfBody><Competition><Session StartDate="{start}" EndDate="{end}"/></Competition></OdfBody>'


P = {"earlier": "StartDate", "later": "EndDate"}


def test_end_after_start_passes():
    assert run("datetime_order", session("2026-01-20", "2026-01-21"), P, ".//Session") == []


def test_end_before_start_is_reported():
    out = run("datetime_order", session("2026-01-21", "2026-01-20"), P, ".//Session")
    assert len(out) == 1
    assert "EndDate" in out[0].message and "StartDate" in out[0].message
    assert "2026-01-20" in out[0].message and "2026-01-21" in out[0].message


def test_equal_is_allowed_by_default():
    assert run("datetime_order", session("2026-01-20", "2026-01-20"), P, ".//Session") == []


def test_equal_can_be_forbidden():
    p = dict(P, allow_equal=False)
    assert len(run("datetime_order", session("2026-01-20", "2026-01-20"), p, ".//Session")) == 1


def test_datetimes_with_offsets_compare_as_instants():
    """10:00+01:00 is 09:00Z, which is before 09:30Z."""
    assert run("datetime_order", session("2026-01-20T10:00:00+01:00", "2026-01-20T09:30:00Z"), P, ".//Session") == []
    assert len(run("datetime_order", session("2026-01-20T10:00:00+01:00", "2026-01-20T08:30:00Z"), P, ".//Session")) == 1


def test_an_unparseable_value_is_skipped_not_reported():
    """Format is value_format's job; this rule only orders what it can read."""
    assert run("datetime_order", session("soon", "2026-01-20"), P, ".//Session") == []


def test_a_missing_attribute_is_skipped():
    xml = '<OdfBody><Competition><Session StartDate="2026-01-20"/></Competition></OdfBody>'
    assert run("datetime_order", xml, P, ".//Session") == []


def test_naive_and_aware_values_are_not_compared():
    """Python refuses to order a naive datetime against an aware one; so do
    we, rather than guessing a zone."""
    assert run("datetime_order", session("2026-01-20T10:00:00", "2026-01-20T09:00:00Z"), P, ".//Session") == []


# --- the pack rules, through the pipeline ---------------------------------

PACK = build_ruleset_pack(Path("Rules/SYOG26"))


def msg(doc_type, disc, body):
    rsc = disc + "-" * 31
    return (f'<OdfBody DocumentType="{doc_type}" DocumentCode="{rsc}" '
            f'CompetitionCode="SYOG2026" Version="1" FeedFlag="P" Date="2026-06-05" '
            f'Time="120000000" LogicalDate="2026-06-05" Source="{disc}1">'
            f'<Competition Gen="1" Sport="1" Codes="1"><Discipline Code="{rsc}"/>{body}'
            f'</Competition></OdfBody>').encode()


def ids(res, rule_id):
    return [f for f in res.findings if f.rule_id == rule_id]


@needs_populated_ruleset
def test_unsorted_partic_teams_is_reported_by_the_pack():
    body = '<Team Code="ATHW100002" Organisation="GER"/><Team Code="ATHM100001" Organisation="GER"/>'
    assert ids(Pipeline().run(msg("DT_PARTIC_TEAMS", "ATH", body), PACK), "GEN_PARTIC_TEAMS_SORT")


@needs_populated_ruleset
def test_sorted_partic_teams_is_not_reported():
    body = '<Team Code="ATHM100001" Organisation="GER"/><Team Code="ATHW100002" Organisation="GER"/>'
    assert not ids(Pipeline().run(msg("DT_PARTIC_TEAMS", "ATH", body), PACK), "GEN_PARTIC_TEAMS_SORT")


@needs_populated_ruleset
def test_session_and_unit_dates_out_of_order_are_reported_by_the_pack():
    body = ('<Session SessionCode="ATH01" StartDate="2026-01-21T10:00:00+01:00" EndDate="2026-01-21T09:00:00+01:00"/>'
            '<Unit Code="ATHM100M-----------FNL-0001----" StartDate="2026-01-21T10:00:00+01:00" EndDate="2026-01-21T09:00:00+01:00"/>')
    res = Pipeline().run(msg("DT_SCHEDULE", "ATH", body), PACK)
    assert ids(res, "GEN_SESSION_DATES_ORDERED") and ids(res, "GEN_UNIT_DATES_ORDERED")
