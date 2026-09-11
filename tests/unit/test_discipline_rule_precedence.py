"""A discipline rule supersedes the generic rule it specialises -- for that
discipline only.

A manual review found GEN_SUBEVENTNAME_CODE produced 370 of 375 warnings in
a SWM run. It validates @SubEventName against EVENT_UNIT ENG_shortDescription
("Heat 2"); SWM_SUBEVENTNAME_CODE validated the same attribute against
ENG_Description ("Men's 50m Backstroke - Heat 2"), which is what the feed
actually sends and what the SWM DD prose asks for. Both rules were active with
no precedence between them, so the generic one fired on every SWM message.

>>> REVERSED LATER. An external review established that the DD's
>>> machine-readable column -- `CC@EVENT_UNIT ENG ShortDescription` -- governs,
>>> and that the prose beside it ("EventUnit ENG Description") is a
>>> documentation defect. Every one of the 24 discipline DDs names
>>> ShortDescription, SWM included (SWM DD line 664). So the 2026-08-12 fix
>>> matched the rule to what the feed sends rather than to what the DD
>>> requires. The 13 discipline rules now use ENG_shortDescription, which makes
>>> them duplicates of the GEN rule and hands the check back to it.
>>>
>>> Consequence, accepted deliberately: SWM messages that send the
>>> ENG_Description form are non-conforming and are reported again -- the same
>>> defect the WST feed was confirmed to have. Those ~370 warnings are true
>>> positives, not the noise the 2026-08-12 audit took them for.

_dedupe_semantic cannot help: it only drops checks that are byte-identical, and
these differ in params.field. What is needed is specialisation -- the narrower
rule wins where it applies, the generic keeps running everywhere else.

The dangerous mistake is suppressing too much. GEN_DOCUMENTSUBCODE_POSINT
(doc_types DT_PRESSPHOTOFINISH_LK, DT_COMMUNICATION) and
ATH_DOCUMENTSUBCODE_POSINT (doc_types DT_IMAGE) share a primitive, target and
attribute but cover DISJOINT document types. The ATH rule does not stand in for
the generic one, so the generic must survive for ATH. That case is pinned below.
"""
from pathlib import Path

from odf_validator.ingestion.builder import build_ruleset_pack
from odf_validator.pipeline.orchestrator import Pipeline
from tests.conftest import needs_populated_ruleset

PACK = build_ruleset_pack(Path("Rules/SYOG26"))


def rsc(disc):
    return disc + "-" * (34 - len(disc))


def run(xml):
    return Pipeline().run(xml.encode("utf-8"), PACK)


def ids(result):
    return {f.rule_id for f in result.findings}


def result_msg(disc, body, doc_type="DT_RESULT", extra=""):
    return ('<OdfBody DocumentType="{}" DocumentCode="{}" '
            'CompetitionCode="SYOG2026" Version="1"{}>'
            '<Competition Gen="SYOG2026-1.0" Sport="SYOG2026-1.0" '
            'Codes="SYOG2026-1.9.1"><Discipline Code="{}"/>{}'
            '</Competition></OdfBody>').format(
                doc_type, rsc(disc), extra, disc, body)


# @SubEventName that is neither an ENG_Description nor an ENG_shortDescription,
# so the surviving rule -- whichever it is -- has something to report.
BAD = ('<ExtendedInfos><SportDescription SubEventName="Not A Real Event Unit"/>'
       '</ExtendedInfos>')


@needs_populated_ruleset
def test_swm_subeventname_still_specialises_the_generic_rule():
    """SWM remains a specialisation; the other twelve no longer are.

    The 2026-09-01 owner decision split them. Twelve disciplines follow the DD
    column (ENG_shortDescription), which makes their rules byte-identical to
    GEN_SUBEVENTNAME_CODE, so _dedupe_semantic absorbs them and the GEN rule
    does the work. SWM keeps ENG_Description, so its rule still differs, still
    survives dedup, and still stands the generic rule down for SWM -- exactly
    the mechanism this module was written to pin.
    """
    res = run(result_msg("SWM", BAD))

    assert "SWM_SUBEVENTNAME_CODE" in ids(res)
    assert "GEN_SUBEVENTNAME_CODE" not in ids(res), [
        f.message for f in res.findings if f.rule_id == "GEN_SUBEVENTNAME_CODE"]


def test_only_swm_keeps_a_discipline_subeventname_rule():
    """The other twelve must stay deduped, or the split has leaked."""
    survivors = {r.id for r in PACK.rules if r.id.endswith("_SUBEVENTNAME_CODE")}

    assert survivors == {"GEN_SUBEVENTNAME_CODE", "SWM_SUBEVENTNAME_CODE"}


def test_specialisation_still_works_where_a_rule_really_does_differ():
    """The mechanism itself, pinned on the one surviving specialisation.

    SAL_FUNCTION_CODE excludes SignedBy (SAL sends a free-text
    Decision/SignedBy/@Function) where GEN_FUNCTION_CODE does not, so it is a
    genuine narrower rule rather than a duplicate, and GEN stands down for SAL.
    """
    gen = [r for r in PACK.rules if r.id == "GEN_FUNCTION_CODE"]

    assert gen, "GEN_FUNCTION_CODE disappeared"
    assert "SAL" in gen[0].applies_to.exclude_disciplines
    assert any(r.id == "SAL_FUNCTION_CODE" for r in PACK.rules)


@needs_populated_ruleset
def test_generic_subeventname_rule_survives_for_undefined_discipline():
    """ARC has no SubEventName rule of its own, so the generic must still run."""
    res = run(result_msg("ARC", BAD))
    assert "GEN_SUBEVENTNAME_CODE" in ids(res)


def test_generic_rule_survives_when_discipline_rule_covers_other_doc_types():
    """ATH_DOCUMENTSUBCODE_POSINT covers DT_IMAGE only; the generic rule covers
    DT_COMMUNICATION. Disjoint scopes -- the generic must not be suppressed."""
    res = run(result_msg("ATH", "", doc_type="DT_COMMUNICATION",
                         extra=' DocumentSubcode="NOTANUMBER"'))
    assert "GEN_DOCUMENTSUBCODE_POSINT" in ids(res), [
        f.rule_id for f in res.findings]
