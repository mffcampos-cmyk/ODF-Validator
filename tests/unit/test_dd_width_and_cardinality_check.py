"""Enforce the field widths and child cardinalities the Data Dictionaries
state and the schema cannot: no xs:maxLength exists in the SYOG26 XSDs, and
the shared competitionType makes every message's children an emptiable
choice, so an empty DT_ENTRIES validates clean.

Both checks run on the restricted sets only (ObligationRegistry.max_widths /
child_bounds with enforceable_only=True), for the reason obligation_check.py
records: a wrong enforcement fires on every matching node in every file.
"""
from pathlib import Path

from lxml import etree

from odf_validator.dispatch import MessageInfo
from odf_validator.ingestion.builder import build_ruleset_pack
from odf_validator.pipeline.cardinality_check import child_count_violations, CARD_RULE
from odf_validator.pipeline.orchestrator import Pipeline
from odf_validator.pipeline.width_check import over_width_attrs, WIDTH_RULE
from odf_validator.rules.obligations import ObligationRegistry
from tests.conftest import needs_populated_ruleset

assert WIDTH_RULE == "CORE_DD_MAX_LENGTH" and CARD_RULE == "CORE_DD_CARDINALITY"


def info(doc_type, discipline):
    return MessageInfo(doc_type, None, None, None, 1, discipline)


def registry():
    r = ObligationRegistry(
        xsd_declared={("Team", "TVTeamName"), ("Team", "Name")},
        xsd_single_owner={("Team", "TVTeamName")},
        xsd_child_declared={("Competition", "Entry"), ("Result", "ExtendedResult")},
        xsd_unambiguous_elements={"Competition", "Result"})
    r.set_general({}, widths={("DT_PARTIC_TEAMS", "Team", "TVTeamName"): 21,
                              ("DT_PARTIC_TEAMS", "Team", "Name"): 73},
                  cardinalities={("DT_ENTRIES", "Competition", "Entry"): (1, None),
                                 ("DT_RESULT", "Result", "ExtendedResult"): (0, 3)})
    r.add_discipline("CRD", {}, widths={("DT_PARTIC_TEAMS", "Team", "TVTeamName"): 40})
    return r


def teams(name):
    return etree.fromstring(f'<OdfBody><Competition><Team TVTeamName="{name}" Name="{name}"/></Competition></OdfBody>')


# --- widths --------------------------------------------------------------

def test_over_width_value_is_reported_with_both_lengths():
    out = over_width_attrs(teams("Federal Republic of Germany"), info("DT_PARTIC_TEAMS", "ATH"), registry())
    assert len(out) == 1
    f = out[0]
    assert f.rule_id == WIDTH_RULE and f.severity.value == "error"
    assert "27" in f.message and "S(21)" in f.message and "TVTeamName" in f.message
    assert f.location.path.endswith("/Team")


def test_value_within_width_is_not_reported():
    assert over_width_attrs(teams("Germany"), info("DT_PARTIC_TEAMS", "ATH"), registry()) == []


def test_exact_width_is_allowed():
    assert over_width_attrs(teams("x" * 21), info("DT_PARTIC_TEAMS", "ATH"), registry()) == []


def test_width_is_counted_in_characters_not_bytes():
    """S(21) is a field width in characters; 'Zürich' is six of them."""
    assert over_width_attrs(teams("Zürich" * 3 + "abc"), info("DT_PARTIC_TEAMS", "ATH"), registry()) == []


def test_discipline_dd_width_overrides_gen():
    """CRD says S(40): a 27-character curling team name is fine."""
    assert over_width_attrs(teams("Federal Republic of Germany"), info("DT_PARTIC_TEAMS", "CRD"), registry()) == []


def test_only_single_owner_pairs_are_enforced():
    """@Name is declared on many elements, so its width is not enforced even
    though the DD states it and the value is over."""
    out = over_width_attrs(teams("x" * 80), info("DT_PARTIC_TEAMS", "ATH"), registry())
    assert [f for f in out if "@Name" in f.message] == []
    assert len(out) == 1


def test_width_is_scoped_by_message():
    assert over_width_attrs(teams("x" * 30), info("DT_RESULT", "ATH"), registry()) == []


def test_exempt_pairs_are_not_enforced():
    """Where a DD states both S(n) and a Common Codes description for the
    same attribute (GEN: Unit/ItemName/@Value, S(40) and the EVENT_UNIT ENG
    description, of which 150 exceed 40), the description governs -- the
    same ruling VenueName and LocationName already have."""
    out = over_width_attrs(teams("x" * 30), info("DT_PARTIC_TEAMS", "ATH"), registry(),
                           exempt={("Team", "TVTeamName")})
    assert out == []


def test_no_registry_means_no_findings():
    assert over_width_attrs(teams("x" * 30), info("DT_PARTIC_TEAMS", "ATH"), None) == []


# --- cardinalities -------------------------------------------------------

def entries(n):
    return etree.fromstring('<OdfBody><Competition>' + '<Entry/>' * n + '</Competition></OdfBody>')


def test_missing_required_child_is_reported_on_the_parent():
    out = child_count_violations(entries(0), info("DT_ENTRIES", "ARC"), registry())
    assert len(out) == 1
    f = out[0]
    assert f.rule_id == CARD_RULE and f.severity.value == "error"
    assert "Entry" in f.message and "(1,N)" in f.message and "0" in f.message
    assert f.location.path.endswith("/Competition")


def test_one_child_satisfies_a_minimum_of_one():
    assert child_count_violations(entries(1), info("DT_ENTRIES", "ARC"), registry()) == []


def test_bound_is_scoped_by_message():
    assert child_count_violations(entries(0), info("DT_RESULT", "ARC"), registry()) == []


def test_too_many_children_is_reported():
    root = etree.fromstring('<OdfBody><Competition><Result>' + '<ExtendedResult/>' * 4 +
                            '</Result><Result><ExtendedResult/></Result></Competition></OdfBody>')
    out = child_count_violations(root, info("DT_RESULT", "ARC"), registry())
    assert len(out) == 1 and "(0,3)" in out[0].message and "4" in out[0].message


def test_no_registry_means_no_cardinality_findings():
    assert child_count_violations(entries(0), info("DT_ENTRIES", "ARC"), None) == []


# --- through the pipeline, against the real pack -------------------------

PACK = build_ruleset_pack(Path("Rules/SYOG26"))


def msg(doc_type, disc, body):
    rsc = disc + "-" * 31
    return (f'<OdfBody DocumentType="{doc_type}" DocumentCode="{rsc}" '
            f'CompetitionCode="SYOG2026" Version="1" FeedFlag="P" Date="2026-06-05" '
            f'Time="120000000" LogicalDate="2026-06-05" Source="{disc}1">'
            f'<Competition Gen="1" Sport="1" Codes="1"><Discipline Code="{rsc}"/>{body}'
            f'</Competition></OdfBody>').encode()


def ids(res, rule):
    return [f for f in res.findings if f.rule_id == rule]


@needs_populated_ruleset
def test_empty_dt_entries_is_reported_through_the_pipeline():
    res = Pipeline().run(msg("DT_ENTRIES", "ARC", ""), PACK)
    assert ids(res, CARD_RULE), [f.message for f in res.findings][:5]


@needs_populated_ruleset
def test_over_width_tvteamname_is_reported_for_ath_and_not_for_crd():
    team = '<Team Code="ATHM100001" Organisation="GER" TVTeamName="Federal Republic of Germany"/>'
    assert ids(Pipeline().run(msg("DT_PARTIC_TEAMS", "ATH", team), PACK), WIDTH_RULE)
    assert not ids(Pipeline().run(msg("DT_PARTIC_TEAMS", "CRD", team), PACK), WIDTH_RULE)


@needs_populated_ruleset
def test_item_name_value_is_exempt_in_the_syog26_pack():
    assert ("ItemName", "Value") in PACK.length_exempt
