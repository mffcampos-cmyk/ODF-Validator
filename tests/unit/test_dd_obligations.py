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
from odf_validator.ingestion.dd_obligations import parse_dd, parse_obligations

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


# ---------------------------------------------------------------------------
# Message-section boundaries.
#
# The parser keys everything on the message named by the last `DocumentType`
# row it saw. The ARC DD for SYOG2026 has a section -- 2.3.3, "List of teams"
# -- that never emits one: its structure table sits under a heading reading
# "Header Values", and the three subsections that normally follow are absent
# from the document. So the parser was still holding DT_PARTIC when it read
# the team structure, and recorded "DT_PARTIC requires Competition/Team (1,N)".
#
# Thirteen other DDs put that same pair under DT_PARTIC_TEAMS. ARC was the only
# document that disagreed, and the only one with no DT_PARTIC_TEAMS section at
# all -- which is what identifies this as mis-attribution rather than a
# sport-specific rule.
# ---------------------------------------------------------------------------

# Trimmed from the real converted ARC DD, keeping the shapes that matter: the
# h2 section heading, the description prose naming both messages, and the
# `Element:` line arriving with no DocumentType row in between.
ARC_LIKE_TEAMS_SECTION = """
## 2.3.2 List of participants by discipline / update

### 2.3.2.2 Header Values

|DocumentType|DT_PARTIC / DT_PARTIC_UPDATE|List of participants by discipline message|
|Element: Competition /Participant (1,N)||||
|Code|M|S(20)|Participant code|

## 2.3.3 List of teams / List of teams update

### 2.3.3.1 Description

DT_PARTIC_TEAMS contains the list of teams related to the current competition.

List of teams update (DT_PARTIC_TEAMS_UPDATE) is an update message.

### 2.3.3.2 Header Values

|Element: Competition /Team (1,N)||||
|Code|M|S(20) with no leading zeroes|Team code|
"""


def test_a_new_message_section_does_not_inherit_the_previous_message():
    """The conservative half: a table nobody can attribute is dropped, not
    attached to whatever came before."""
    facts = parse_dd(ARC_LIKE_TEAMS_SECTION)
    assert ("DT_PARTIC", "Competition", "Team") not in facts.cardinalities
    assert ("DT_PARTIC_UPDATE", "Competition", "Team") not in facts.cardinalities
    assert ("DT_PARTIC", "Team", "Code") not in facts.obligations


def test_a_section_naming_its_message_in_prose_is_recovered():
    """The recovery half: the document says which message it is describing in
    words, so the rows are keyed to that message rather than lost."""
    facts = parse_dd(ARC_LIKE_TEAMS_SECTION)
    assert facts.cardinalities[("DT_PARTIC_TEAMS", "Competition", "Team")] == (1, None)
    assert facts.cardinalities[("DT_PARTIC_TEAMS_UPDATE", "Competition", "Team")] == (1, None)
    assert facts.obligations[("DT_PARTIC_TEAMS", "Team", "Code")] == "M"


def test_the_message_before_the_boundary_is_untouched():
    facts = parse_dd(ARC_LIKE_TEAMS_SECTION)
    assert facts.cardinalities[("DT_PARTIC", "Competition", "Participant")] == (1, None)
    assert facts.obligations[("DT_PARTIC", "Participant", "Code")] == "M"


# GEN writes its message sections as h3 and their subsections as h4; ARC writes
# the same two levels as h2 and h3. A boundary rule keyed on markdown depth
# therefore works for one document and silently does nothing for the other --
# which is why the rule is keyed on the section NUMBERING both carry.
GEN_LIKE_DEEPER_HEADINGS = """
### 2.1.35 Background Document

#### 2.1.35.2 Header Values

|DocumentType|DT_PDF|Background document message|
|Element: Competition /Document (1,N)||||
|Code|M|S(20)|Document code|

### 2.1.39 Team Biography

#### 2.1.39.5 Message Values

|Element: Competition /Language /GInterest (0,1)||||
|Nickname|O|S(25)|Nickname|
"""


def test_section_boundaries_are_found_whatever_the_heading_depth():
    facts = parse_dd(GEN_LIKE_DEEPER_HEADINGS)
    assert facts.cardinalities[("DT_PDF", "Competition", "Document")] == (1, None)
    assert ("DT_PDF", "Language", "GInterest") not in facts.cardinalities
    assert ("DT_PDF", "GInterest", "Nickname") not in facts.obligations


SUBSECTION_HEADINGS = """
### 2.3.5 Event Unit Start List and Results

#### 2.3.5.2 Header Values

|DocumentType|DT_RESULT|Event Unit Start List and Results message|

#### 2.3.5.4 Message Structure

### Message Values

|Element: Competition /Result (1,N)||||
|SortOrder|M|Positive Integer|Used to sort all the results|
"""


def test_subsection_headings_do_not_end_the_message():
    """Only the section level ends a message. Every DD puts its structure and
    values tables under headings deeper than the one naming the message, and an
    unnumbered heading (`### Message Values`, which ARC emits) says nothing
    about sections at all. Clearing on either would discard every cardinality
    in every document."""
    facts = parse_dd(SUBSECTION_HEADINGS)
    assert facts.cardinalities[("DT_RESULT", "Competition", "Result")] == (1, None)
    assert facts.obligations[("DT_RESULT", "Result", "SortOrder")] == "M"


PROSE_THEN_REAL_HEADER = """
## 2.3.2 List of participants by discipline

### 2.3.2.1 Description

The DT_PARTIC message is sent as a bulk message prior to the Games, after
which only DT_PARTIC_UPDATE messages are sent.

|DocumentType|DT_ENTRIES|List of entries by event message|
|Element: Competition /Entry (1,N)||||
|Code|M|S(20)|Entry code|
"""


def test_a_real_header_row_overrides_anything_recovered_from_prose():
    """Recovery fills a gap; it never competes with the document saying so
    itself. Prose names other messages freely -- the DT_PARTIC section's own
    description mentions DT_PARTIC_UPDATE in passing -- so a recovered name
    must lose to the next DocumentType row."""
    facts = parse_dd(PROSE_THEN_REAL_HEADER)
    assert facts.cardinalities[("DT_ENTRIES", "Competition", "Entry")] == (1, None)
    assert ("DT_PARTIC", "Competition", "Entry") not in facts.cardinalities
    assert ("DT_PARTIC_UPDATE", "Competition", "Entry") not in facts.cardinalities
