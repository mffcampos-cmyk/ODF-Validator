"""The Data Dictionaries state field widths and child cardinalities in the
same rows and headings the M/O parser already reads, one cell further along.

`|TVTeamName|M|S(21)|TV Team Name|` -- the S(21) is the cell after the M/O.
`Element: Competition /Entry (1,N)` -- the bound follows the element path.

Both are keyed exactly like obligations: (doc_type, element, attribute) for a
width, (doc_type, parent, child) for a cardinality. Attribute name alone is
never enough -- across the SYOG26 DDs @Value is declared at fifteen different
widths (S(1) to S(255)) depending on the element that carries it, and @Code at
S(3), S(6), S(15), S(20) and S(40). A width keyed on the name would report a
valid 34-character RSC as over a 20-character limit.
"""
from odf_validator.ingestion.dd_obligations import parse_dd, parse_obligations
from odf_validator.ingestion.obligation_store import ObligationStore, PARSER_VERSION

GEN_LIKE = """
|DocumentType|DT_PARTIC_TEAMS|Team participants message|
|Element: Competition (0,1)||||
|Gen|M|S(20)|Version of the General Data Dictionary|
|Element: Competition /Team (1,N)||||
|Attribute|M/O|Value|Description|
|Code|M|S(20)|Team's ID|
|TVTeamName|M|S(21)|TV Team Name|
|Order|O|Positive Integer|Display order|
|Element: Competition /Team /Composition (0,1)||||
|Element: Competition /Team /Composition /Athlete (1,N)||||
|Code|M|S(20)|Athlete's ID|
|DocumentType|DT_SCHEDULE|Schedule message|
|Element: Competition /Session (0,N)||||
|Code|M|S(40)|Session code|
|Element: Competition /Unit /ItemName (1,N)||||
|Value|M|S( 40 )|Item Name / Unit Description|
|Element: Competition /Unit /VenueDescription (0,1)||||
|VenueName|M|CC@VENUE|Venue ENG Description|
"""


def test_width_is_read_from_the_cell_after_the_obligation():
    facts = parse_dd(GEN_LIKE)
    assert facts.widths[("DT_PARTIC_TEAMS", "Team", "TVTeamName")] == 21


def test_a_value_cell_that_is_not_a_width_yields_no_width():
    facts = parse_dd(GEN_LIKE)
    assert ("DT_PARTIC_TEAMS", "Team", "Order") not in facts.widths
    assert ("DT_SCHEDULE", "VenueDescription", "VenueName") not in facts.widths


def test_width_is_keyed_by_element_not_by_attribute_name():
    """@Code is S(20) on Team and S(40) on Session in the same document."""
    facts = parse_dd(GEN_LIKE)
    assert facts.widths[("DT_PARTIC_TEAMS", "Team", "Code")] == 20
    assert facts.widths[("DT_SCHEDULE", "Session", "Code")] == 40


def test_width_tolerates_spacing_inside_the_parentheses():
    """PDF conversion leaves `S( 40 )` as often as `S(40)`."""
    facts = parse_dd(GEN_LIKE)
    assert facts.widths[("DT_SCHEDULE", "ItemName", "Value")] == 40


def test_obligations_are_unchanged_by_the_richer_parse():
    """parse_obligations() is what the committed cache and the registry
    consume today; parse_dd() must agree with it exactly."""
    assert parse_dd(GEN_LIKE).obligations == parse_obligations(GEN_LIKE)
    assert parse_dd(GEN_LIKE).obligations[("DT_PARTIC_TEAMS", "Team", "TVTeamName")] == "M"


def test_cardinality_is_read_from_the_element_heading():
    facts = parse_dd(GEN_LIKE)
    assert facts.cardinalities[("DT_PARTIC_TEAMS", "Competition", "Team")] == (1, None)
    assert facts.cardinalities[("DT_PARTIC_TEAMS", "Team", "Composition")] == (0, 1)
    assert facts.cardinalities[("DT_PARTIC_TEAMS", "Composition", "Athlete")] == (1, None)


def test_cardinality_is_scoped_by_message():
    facts = parse_dd(GEN_LIKE)
    assert facts.cardinalities[("DT_SCHEDULE", "Competition", "Session")] == (0, None)
    assert ("DT_PARTIC_TEAMS", "Competition", "Session") not in facts.cardinalities


def test_the_root_element_has_no_parent_and_no_cardinality_row():
    """`Element: Competition (0,1)` bounds the document root's only child;
    the schema already fixes that and there is no parent to key it on."""
    facts = parse_dd(GEN_LIKE)
    assert not any(child == "Competition" for _, _, child in facts.cardinalities)


def test_cardinality_tolerates_a_leading_zero_and_spaces():
    """The SYOG26 DDs contain one `(01,N)` and several `( 0 , 3 )`."""
    md = """
|DocumentType|DT_RESULT|Results|
|Element: Competition /Result (01,N)||||
|Element: Competition /Result /ExtendedResult ( 0 , 3 )||||
"""
    facts = parse_dd(md)
    assert facts.cardinalities[("DT_RESULT", "Competition", "Result")] == (1, None)
    assert facts.cardinalities[("DT_RESULT", "Result", "ExtendedResult")] == (0, 3)


def test_a_heading_without_bounds_records_no_cardinality():
    md = """
|DocumentType|DT_RESULT|Results|
|Element: Competition /Result||||
|Rank|O|Positive Integer|Rank|
"""
    facts = parse_dd(md)
    assert facts.cardinalities == {}
    assert ("DT_RESULT", "Result", "Rank") in facts.obligations


def test_width_inside_a_per_code_block_is_recorded_for_the_element():
    """Extension-style tables state one width per @Code. The first width seen
    for a key stands; a per-code difference in width has not been observed in
    the SYOG26 DDs and is not modelled."""
    md = """
|DocumentType|DT_RESULT|Results|
|Element: Competition /Result /ExtendedResult (0,N)||||
||Type|Code|Pos|Description|
|ER||B_JUDGE|Numeric #0|Pos Description|
|Attribute|M/O|Value|Description|
|Value|M|S(10)|Judges score|
"""
    facts = parse_dd(md)
    assert facts.widths[("DT_RESULT", "ExtendedResult", "Value")] == 10
    assert facts.obligations[("DT_RESULT", "ExtendedResult", "Value")] == "M@B_JUDGE"


# --- the committed cache carries the new facts ---------------------------

def test_store_round_trips_widths_and_cardinalities(tmp_path):
    p = tmp_path / "ob.json"
    facts = parse_dd(GEN_LIKE)
    s = ObligationStore.load(p)
    s.put_facts("a/b.pdf", "h", facts)
    s.save()
    back = ObligationStore.load(p).get_facts("a/b.pdf", "h")
    assert back.obligations == facts.obligations
    assert back.widths == facts.widths
    assert back.cardinalities == facts.cardinalities


def test_store_get_still_serves_obligations_only(tmp_path):
    p = tmp_path / "ob.json"
    s = ObligationStore.load(p)
    s.put_facts("a/b.pdf", "h", parse_dd(GEN_LIKE))
    assert s.get("a/b.pdf", "h") == parse_obligations(GEN_LIKE)


def test_parser_version_was_bumped_for_the_new_columns():
    """Cache entries are keyed on the DD's content hash, which does not change
    when the parser learns a new column. Without a bump every entry written by
    parser 2 would be served as complete and no width would ever be enforced."""
    assert PARSER_VERSION >= 3


def test_an_entry_from_parser_2_has_no_widths_and_is_a_miss(tmp_path):
    import json
    p = tmp_path / "ob.json"
    p.write_text(json.dumps({"a/b.pdf": {"hash": "h", "parser": 2,
                                          "obligations": [["DT_X", "E", "A", "M"]]}}))
    assert ObligationStore.load(p).get_facts("a/b.pdf", "h") is None


def test_an_element_heading_with_an_empty_path_does_not_crash():
    """Seen in the real SYOG26 conversions: an `Element:` line whose path is
    empty. The rows under it cannot be attributed and are skipped, as before."""
    md = """
|DocumentType|DT_RESULT|Results|
|Element: (0,1)||||
|Rank|O|Positive Integer|Rank|
"""
    facts = parse_dd(md)
    assert facts.obligations == {} and facts.cardinalities == {}
