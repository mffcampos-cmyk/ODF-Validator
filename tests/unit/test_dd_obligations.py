"""Parsing M/O obligations out of a converted Data Dictionary.

The sport Data Dictionary is the final authority on whether an attribute is
mandatory, ahead of the schema. The shared
odf2-structure.xsd has ONE competitionType used by every message type, so
use="required" there cannot express "mandatory for DT_ENTRIES, optional for
DT_RESULT" -- only the DD can. To act on the DD we first have to read it.

Obligations are keyed on (doc_type, element, attribute). Attribute name alone is
never enough: `Code` is required on 83 complexTypes, and a DD marking
Result/@Rank optional says nothing about MedalLine/@Rank.
"""
from odf_validator.ingestion.dd_obligations import parse_obligations

SWM_LIKE = """
|DocumentType|DT_ENTRIES|List of entries by event message|
|Element: Competition (0,1)||||
|---|---|---|---|
|Attribute|M/O|Value|Description|
|Gen|M|S(20)|Version of the General Data Dictionary|
|Codes|M|S(20)|Version of the Codes|
|DocumentType|DT_RESULT|Event Unit Start List and Results message|
|Element: Competition (0,1)||||
|Gen|O|S(20)|Version of the General Data Dictionary|
|Element: Competition /Result (1,N)||||
|SortOrder|M|Positive Integer|Used to sort all the results|
|Rank|O|Positive Integer|Rank of the competitor|
"""


def test_reads_mandatory_and_optional_for_one_message():
    ob = parse_obligations(SWM_LIKE)
    assert ob[("DT_ENTRIES", "Competition", "Gen")] == "M"
    assert ob[("DT_RESULT", "Competition", "Gen")] == "O"


def test_same_attribute_differs_by_message():
    """The whole point: one attribute, two obligations, keyed by doc_type."""
    ob = parse_obligations(SWM_LIKE)
    assert ob[("DT_ENTRIES", "Competition", "Gen")] != \
           ob[("DT_RESULT", "Competition", "Gen")]


def test_element_context_is_tracked_not_just_attribute_name():
    ob = parse_obligations(SWM_LIKE)
    assert ob[("DT_RESULT", "Result", "SortOrder")] == "M"
    assert ("DT_RESULT", "Competition", "SortOrder") not in ob


def test_nested_element_path_uses_leaf_name():
    ob = parse_obligations(SWM_LIKE)
    assert ("DT_RESULT", "Result", "Rank") in ob


def test_header_with_padded_empty_cells_is_recognised():
    """BS5 writes `||DocumentType||DT_ENTRIES|`. A parser that misses this
    attributes DT_ENTRIES rows to the PREVIOUS message -- which during the
    2026-08-14 survey produced a phantom 'BS5 marks Gen mandatory for
    DT_PARTIC_TEAMS' finding that did not exist in the document."""
    ob = parse_obligations(
        "|DocumentType|DT_PARTIC_TEAMS|teams|\n"
        "|Element: Competition (0,1)||||\n"
        "|Gen|O|S(20)|x|\n"
        "||DocumentType||DT_ENTRIES|List of entries by event message|\n"
        "|Element: Competition (0,1)||||\n"
        "|Gen|M|S(20)|x|\n")
    assert ob[("DT_PARTIC_TEAMS", "Competition", "Gen")] == "O"
    assert ob[("DT_ENTRIES", "Competition", "Gen")] == "M"


def test_combined_header_applies_to_every_listed_message():
    ob = parse_obligations(
        "|DocumentType|DT_PARTIC / DT_PARTIC_UPDATE|participants|\n"
        "|Element: Competition (0,1)||||\n"
        "|Gen|O|S(20)|x|\n")
    assert ob[("DT_PARTIC", "Competition", "Gen")] == "O"
    assert ob[("DT_PARTIC_UPDATE", "Competition", "Gen")] == "O"


def test_rows_before_any_message_header_are_ignored():
    ob = parse_obligations("|Element: Competition (0,1)||||\n|Gen|M|S(20)|x|\n")
    assert ob == {}


def test_table_header_row_is_not_read_as_an_obligation():
    ob = parse_obligations(SWM_LIKE)
    assert not any(a == "Attribute" for _, _, a in ob)


def test_letter_spaced_header_from_pdf_conversion_is_recognised():
    """The GEN DD's PDF tracking survives conversion as spaces inside words:

        |D oc ume ntTy p e|DT_R ES ULT|Event Unit Start List and Results|

    51 of the GEN DD's 51 message sections are written this way and exactly one
    is not. A parser that only matches the clean spelling attributes all 602 of
    the GEN obligations to that single message (DT_ENTRIES).
    """
    ob = parse_obligations(
        "|D oc ume ntTy p e|DT_R ES ULT|Event Unit Start List and Results|\n"
        "|Element: Competition (0,1)||||\n"
        "|Gen|O|S(20)|x|\n")
    assert ob[("DT_RESULT", "Competition", "Gen")] == "O"


def test_letter_spaced_header_listing_two_messages_splits_them():
    """`DT_SCHEDULE DT_SCHEDULE_UPDATE` collapses to DT_SCHEDULEDT_SCHEDULE_UPDATE
    once the spacing is stripped, and must split back into both names -- not one
    concatenation, and not just the shared prefix."""
    ob = parse_obligations(
        "|D oc ume ntTy p e|DT_SCHEDULE DT_SCHEDULE_UPDATE|schedule|\n"
        "|Element: Competition (0,1)||||\n"
        "|Gen|M|S(20)|x|\n")
    assert ob[("DT_SCHEDULE", "Competition", "Gen")] == "M"
    assert ob[("DT_SCHEDULE_UPDATE", "Competition", "Gen")] == "M"
    assert not any(dt.count("DT_") > 1 for dt, _, _ in ob)


def test_an_attribute_row_named_documenttype_is_not_a_section_header():
    """`|D oc ume ntTy p e|M|S(30)|DocumentType of the original message|` is an
    attribute definition inside DT_NOTIFICATION, not a new section."""
    ob = parse_obligations(
        "|DocumentType|DT_NOTIFICATION|notification|\n"
        "|Element: Competition (0,1)||||\n"
        "|D oc ume ntTy p e|M|S(30)|DocumentType of the original message|\n"
        "|Gen|M|S(20)|x|\n")
    assert ob[("DT_NOTIFICATION", "Competition", "Gen")] == "M"
