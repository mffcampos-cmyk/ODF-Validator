from odf_validator.ingestion.dd_parser import extract_draft_rules

# Verbatim from docs/source/ODF_GEN_R-OWG2026-GEN.md line 1066 — the exact
# source line the hand-authored GEN_VENUE_CODE rule
# (odf_validator/rules/defs/gen/common.yaml) already encodes.
GEN_VENUE_LINE = "Venue M CC@VENUE Venue where the session takes place"

# Verbatim from docs/source/ODF_ARC_Data_Dictionary.md line 352.
ARC_VERSION_LINE = ("Version  Positive Integer  Version number associated to "
                     "the message's content. Ascending number")


def test_cc_reference_extracts_code_membership_matching_existing_hand_rule():
    drafts = extract_draft_rules(GEN_VENUE_LINE, discipline=None, source_name="GEN.md")
    assert len(drafts) == 1
    d = drafts[0]
    # Same id as the hand-authored GEN_VENUE_CODE rule: a re-derivation of the
    # same DD line must line up with what a human already approved by hand.
    assert d.id == "GEN_VENUE_CODE"
    assert d.primitive == "code_membership"
    assert d.target == ".//*[@Venue]"
    assert d.attribute == "Venue"
    assert d.params == {"codeset": "VENUE"}
    assert d.severity == "warning"
    assert d.scope == "message"
    assert d.applies_to == {}
    assert d.status == "draft"
    assert "GEN.md" in d.source_ref


def test_cc_reference_with_discipline_scopes_applies_to():
    drafts = extract_draft_rules(GEN_VENUE_LINE, discipline="ARC",
                                  source_name="ARC_DD.md")
    assert drafts[0].id == "ARC_VENUE_CODE"
    assert drafts[0].applies_to == {"disciplines": ["ARC"]}


def test_positive_integer_extracts_value_format():
    drafts = extract_draft_rules(ARC_VERSION_LINE, discipline="ARC",
                                  source_name="ARC_DD.md")
    assert len(drafts) == 1
    d = drafts[0]
    assert d.id == "ARC_VERSION_POSINT"
    assert d.primitive == "value_format"
    assert d.target == ".//*[@Version]"
    assert d.attribute == "Version"
    assert d.params == {"regex": "^[0-9]+$"}
    assert d.severity == "error"


def test_unmatched_prose_extracts_nothing():
    text = ("Mandatory when unit is phase or event unit. This is free-form "
            "conditional prose the heuristic parser must not guess at.")
    assert extract_draft_rules(text, discipline="ARC", source_name="x.md") == []


def test_pipe_table_row_is_normalized_before_matching():
    row = "| Venue | M | CC@VENUE | Venue where the session takes place |"
    drafts = extract_draft_rules(row, discipline=None, source_name="GEN.md")
    assert len(drafts) == 1
    assert drafts[0].id == "GEN_VENUE_CODE"


def test_duplicate_lines_do_not_duplicate_the_same_rule_id():
    text = f"{GEN_VENUE_LINE}\n{GEN_VENUE_LINE}"
    drafts = extract_draft_rules(text, discipline=None, source_name="GEN.md")
    assert len(drafts) == 1


def test_to_yaml_dict_matches_rule_loader_shape():
    drafts = extract_draft_rules(GEN_VENUE_LINE, discipline=None, source_name="GEN.md")
    d = drafts[0].to_yaml_dict()
    assert set(d) == {"id", "applies_to", "primitive", "target", "attribute",
                       "params", "severity", "scope", "source_ref", "status"}


def test_codeset_is_normalized_to_uppercase():
    line = "Venue M CC@venue Venue where the session takes place"
    drafts = extract_draft_rules(line, discipline=None, source_name="x.md")
    assert drafts[0].params == {"codeset": "VENUE"}


def test_casing_collision_produces_separate_drafts_not_silent_drop():
    text = ("Venue M CC@VENUE Venue where the session takes place\n"
            "VENUE M CC@VENUE Venue where the unit takes place")
    drafts = extract_draft_rules(text, discipline=None, source_name="x.md")
    # Both survive even though they'd collide to the same uppercase rule_id -
    # the second must not silently vanish just because casing differs.
    assert len(drafts) == 2
    assert {d.attribute for d in drafts} == {"Venue", "VENUE"}


def test_generic_version_positint_is_suppressed_as_core_owned():
    # The generic "Version is a positive integer" check is owned by the
    # immutable core layer (CORE_VERSION_POSINT). Re-extracting it as a GEN_
    # pack rule duplicates core and wrongly plants an engine-wide check inside a
    # game pack, so the generic (discipline=None) parser must NOT emit it.
    drafts = extract_draft_rules(ARC_VERSION_LINE, discipline=None, source_name="GEN.md")
    assert [d.id for d in drafts] == []


def test_generic_code_value_attrs_are_not_turned_into_unscoped_code_rules():
    # "Code" and "Value" are generic ODF container attributes whose valid
    # codeset depends on a sibling Type/context. A blanket .//*[@Code] or
    # .//*[@Value] code_membership rule matches unrelated elements and floods
    # the report with false positives (observed: ~110k warnings on one message
    # set), so the parser must not emit them -- for GEN or for a discipline.
    for disc in (None, "ARC"):
        code = extract_draft_rules("Code M CC@EVENT_UNIT Full RSC for the unit",
                                   discipline=disc, source_name="DD.md")
        value = extract_draft_rules("Value O CC@EVENT_UNIT Item name / unit description",
                                    discipline=disc, source_name="DD.md")
        # ...and a generic "Value Positive Integer" line must not become a rule
        # either (an unscoped .//*[@Value] numeric check is equally overbroad).
        value_int = extract_draft_rules("Value O Positive Integer Item value",
                                        discipline=disc, source_name="DD.md")
        assert [d.id for d in code] == [] and [d.id for d in value] == [] \
            and [d.id for d in value_int] == [], f"disc={disc}"


def test_name_description_fields_are_not_turned_into_code_rules():
    # DD lists *Name fields with a CC@ reference but annotates them "ENG
    # Description (not code) from Common Codes": VenueName holds "Tokyo
    # Metropolitan Gym", not the VENUE code "TGY". Turning them into
    # code_membership rules flags every description as an invalid code, so the
    # parser must skip any field whose name ends in "Name" (any discipline).
    for disc in (None, "BKG"):
        for line in [
            "VenueName M CC@VENUE Venue ENG Description (not code) from Common Codes",
            "DisciplineName M CC@DISCIPLINE Discipline ENG Description (not code)",
            "EventName M CC@EVENT Event ENG Description (not code) from Common Codes",
            "SubEventName M CC@EVENT_UNIT EventUnit ENG Description (not code)",
            "LocationName M CC@LOCATION Location ENG Description (not code)",
        ]:
            drafts = extract_draft_rules(line, discipline=disc, source_name="DD.md")
            assert [d.id for d in drafts] == [], f"{disc}: {line[:20]}"


def test_context_dependent_code_attrs_are_not_turned_into_rules():
    # @Sport is a version string on <Competition> ("SOG-2024-BKG-1.1") but a
    # sport code elsewhere; @Gender is PERSON_GENDER on a participant but
    # SPORT_GENDER (M/W/O/...) on an event. An unscoped .//*[@Sport]/.//*[@Gender]
    # rule can't tell the contexts apart and false-flags the valid ones, so the
    # parser must not emit them.
    for disc in (None, "BKG"):
        sport = extract_draft_rules("Sport M CC@SPORT Sport Code where applicable",
                                    discipline=disc, source_name="DD.md")
        gender = extract_draft_rules("Gender M CC@PERSON_GENDER Participant's gender",
                                     discipline=disc, source_name="DD.md")
        assert [d.id for d in sport] == [] and [d.id for d in gender] == [], disc
