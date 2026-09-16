"""Field widths and child cardinalities follow the same authority chain as
M/O obligations: discipline DD, then GEN DD. The schema contributes nothing
here (there is no xs:maxLength in the SYOG26 XSDs), but it still decides what
is safe to enforce, exactly as for mandatory attributes.

The case that makes precedence matter: the GEN DD and thirteen discipline DDs
declare Team/@TVTeamName as S(21); the CRD DD declares it S(40). A GEN-derived
limit applied to curling would report a valid 30-character name.
"""
from odf_validator.rules.obligations import ObligationRegistry

GEN_W = {("DT_PARTIC_TEAMS", "Team", "TVTeamName"): 21,
         ("DT_PARTIC_TEAMS", "Team", "Name"): 73,
         ("DT_SCHEDULE", "Session", "Code"): 40}
CRD_W = {("DT_PARTIC_TEAMS", "Team", "TVTeamName"): 40}


def reg(**kw):
    r = ObligationRegistry(
        xsd_required=kw.pop("xsd_required", set()),
        xsd_declared=kw.pop("xsd_declared", set()),
        xsd_unambiguous=kw.pop("xsd_unambiguous", set()),
        xsd_child_declared=kw.pop("xsd_child_declared", set()),
        xsd_child_required=kw.pop("xsd_child_required", set()),
        xsd_child_single=kw.pop("xsd_child_single", set()),
        xsd_unambiguous_elements=kw.pop("xsd_unambiguous_elements", set()),
        xsd_single_owner=kw.pop("xsd_single_owner", set()))
    for disc, (ob, w, c) in kw.pop("disciplines", {}).items():
        r.add_discipline(disc, ob, widths=w, cardinalities=c)
    if "general" in kw:
        ob, w, c = kw.pop("general")
        r.set_general(ob, widths=w, cardinalities=c)
    return r


# --- widths --------------------------------------------------------------

def test_discipline_width_beats_gen_width():
    r = reg(general=({}, GEN_W, {}), disciplines={"CRD": ({}, CRD_W, {})})
    assert r.max_widths("CRD", "DT_PARTIC_TEAMS")[("Team", "TVTeamName")] == 40


def test_gen_width_applies_where_the_sport_dd_is_silent():
    r = reg(general=({}, GEN_W, {}), disciplines={"CRD": ({}, CRD_W, {})})
    assert r.max_widths("ARC", "DT_PARTIC_TEAMS")[("Team", "TVTeamName")] == 21
    # the full RSC spelling dispatch() reports resolves like the bare code
    assert r.max_widths("CRD" + "-" * 31, "DT_PARTIC_TEAMS")[("Team", "TVTeamName")] == 40


def test_widths_are_scoped_by_message():
    r = reg(general=({}, GEN_W, {}))
    assert ("Session", "Code") not in r.max_widths(None, "DT_PARTIC_TEAMS")
    assert r.max_widths(None, "DT_SCHEDULE") == {("Session", "Code"): 40}


def test_a_width_on_a_pair_the_schema_does_not_declare_is_dropped():
    """Same floor as _keep() for obligations: a converted-PDF table can
    attribute a row to the wrong element, and an undeclared pair proves it."""
    r = reg(xsd_declared={("Team", "TVTeamName")}, general=({}, GEN_W, {}))
    assert r.max_widths(None, "DT_PARTIC_TEAMS") == {("Team", "TVTeamName"): 21}


def test_enforceable_widths_are_only_the_single_owner_pairs():
    """@Name is declared on many elements; @TVTeamName on one complexType.
    <Team> itself maps to three types, which would bar it from the presence
    check -- but a node CARRYING @TVTeamName can only be the one type that
    declares it, so its width is safe to check."""
    r = reg(xsd_single_owner={("Team", "TVTeamName")}, general=({}, GEN_W, {}))
    assert r.max_widths(None, "DT_PARTIC_TEAMS", enforceable_only=True) == \
        {("Team", "TVTeamName"): 21}


def test_no_schema_information_means_nothing_is_enforceable():
    r = reg(general=({}, GEN_W, {}))
    assert r.max_widths(None, "DT_PARTIC_TEAMS", enforceable_only=True) == {}


# --- cardinalities -------------------------------------------------------

GEN_C = {("DT_ENTRIES", "Competition", "Entry"): (1, None),
         ("DT_RESULT", "Competition", "Result"): (1, None),
         ("DT_RESULT", "Result", "ExtendedResult"): (0, 3),
         ("DT_ENTRIES", "Description", "Extra"): (1, None)}


def test_discipline_bounds_beat_gen_bounds():
    r = reg(general=({}, {}, GEN_C),
            disciplines={"SWM": ({}, {}, {("DT_ENTRIES", "Competition", "Entry"): (0, None)})})
    assert r.child_bounds("SWM", "DT_ENTRIES")[("Competition", "Entry")] == (0, None)
    assert r.child_bounds("ARC", "DT_ENTRIES")[("Competition", "Entry")] == (1, None)


def test_bounds_are_scoped_by_message():
    r = reg(general=({}, {}, GEN_C))
    assert ("Competition", "Result") not in r.child_bounds(None, "DT_ENTRIES")


def test_an_undeclared_parent_child_pair_is_dropped():
    r = reg(xsd_child_declared={("Competition", "Entry")}, general=({}, {}, GEN_C))
    assert r.child_bounds(None, "DT_RESULT") == {}
    assert r.child_bounds(None, "DT_ENTRIES") == {("Competition", "Entry"): (1, None)}


def test_enforceable_bounds_need_an_unambiguous_parent():
    """<Description> is 13 complexTypes; a bound stated for one of them must
    not be demanded of the other twelve."""
    r = reg(xsd_unambiguous_elements={"Competition"}, general=({}, {}, GEN_C))
    out = r.child_bounds(None, "DT_ENTRIES", enforceable_only=True)
    assert out == {("Competition", "Entry"): (1, None)}


def test_enforceable_bounds_leave_the_schema_what_it_already_requires():
    """The shared competitionType has minOccurs=1 on Result; the XSD reports a
    missing Result itself. Entry is emptiable in the schema, so (1,N) from the
    DD is the only thing that catches an empty DT_ENTRIES."""
    r = reg(xsd_unambiguous_elements={"Competition", "Result"},
            xsd_child_required={("Competition", "Result")},
            general=({}, {}, GEN_C))
    assert ("Competition", "Result") not in r.child_bounds(None, "DT_RESULT", enforceable_only=True)
    assert r.child_bounds(None, "DT_ENTRIES", enforceable_only=True) == \
        {("Competition", "Entry"): (1, None)}


def test_enforceable_bounds_keep_a_maximum_the_schema_does_not_cap():
    r = reg(xsd_unambiguous_elements={"Competition", "Result"},
            xsd_child_required={("Competition", "Result")},
            general=({}, {}, GEN_C))
    assert r.child_bounds(None, "DT_RESULT", enforceable_only=True) == \
        {("Result", "ExtendedResult"): (0, 3)}


def test_enforceable_bounds_drop_a_maximum_the_schema_already_caps_at_one():
    r = reg(xsd_unambiguous_elements={"Result"},
            xsd_child_single={("Result", "ExtendedResult")},
            general=({}, {}, {("DT_RESULT", "Result", "ExtendedResult"): (0, 1)}))
    assert r.child_bounds(None, "DT_RESULT", enforceable_only=True) == {}
