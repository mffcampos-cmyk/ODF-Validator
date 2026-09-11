"""Regression guard: unscoped generic attributes must not carry an unscoped
`code_membership` rule.

Root cause (2026-07-16): GEN + 13 discipline rulesets shipped stale
`code_membership` rules on `@Gender` (codeset PERSON_GENDER) and `@Sport`
(codeset SPORT) with an unscoped `.//*[@X]` target. These predate the
dd_parser guard (`_UNSCOPED_GENERIC_ATTRS`) that deliberately never emits them,
because the attribute's codeset is context-dependent:
  - Gender -> PERSON_GENDER on a participant but SPORT_GENDER (M/W/O/...) on an
    event/SportDescription.
  - Sport  -> a version string on <Competition> ("SOG-2024-BKG-1.1"), a sport
    code only elsewhere.
An unscoped check therefore floods every real document with false positives,
e.g. `@Gender='W' is not a valid PERSON_GENDER code.` and
`@Sport='SOG-2024-BKG-1.1' is not a valid SPORT code.` (see odf-validation (6)).
BKG's ruleset was already cleaned; these tests lock the same contract for every
pack and reproduce the two exact false positives.
"""
from pathlib import Path

from odf_validator.ingestion.builder import build_ruleset_pack
from odf_validator.ingestion.dd_parser import _UNSCOPED_GENERIC_ATTRS
from odf_validator.pipeline.orchestrator import Pipeline

PACK = build_ruleset_pack(Path("Rules/SYOG26"))
RSC = "BKG" + "-" * 31  # valid 34-char RSC document code


def _partic_xml(gender="W", sport="SOG-2024-BKG-1.1"):
    return (
        f'<OdfBody DocumentType="DT_PARTIC" DocumentCode="{RSC}" '
        f'CompetitionCode="SYOG2026" Version="1">'
        f'<Competition Sport="{sport}"><Discipline Code="BKG"/>'
        f'<Participant><Composition><Athlete>'
        f'<Description Gender="{gender}"/>'
        f'</Athlete></Composition></Participant>'
        f'</Competition></OdfBody>'
    )


def _run(xml):
    return Pipeline().run(xml.encode("utf-8"), PACK)


def test_no_active_code_membership_on_unscoped_generic_attrs():
    offenders = [
        r.id for r in PACK.rules
        if r.primitive == "code_membership"
        and getattr(r, "attribute", None) in _UNSCOPED_GENERIC_ATTRS
        and getattr(r, "target", "") == f".//*[@{r.attribute}]"
    ]
    assert offenders == [], (
        "Unscoped code_membership rules on context-dependent attributes flood "
        f"false positives; remove these stale rules: {offenders}"
    )


def test_participant_gender_W_not_flagged_as_invalid_person_gender():
    msgs = [f.message for f in _run(_partic_xml(gender="W")).findings]
    assert not any("is not a valid PERSON_GENDER" in m for m in msgs), msgs


def test_competition_sport_version_string_not_flagged_as_invalid_sport():
    msgs = [f.message for f in _run(_partic_xml()).findings]
    assert not any("is not a valid SPORT code" in m for m in msgs), msgs
