"""Authority order for "is this attribute mandatory?": discipline DD, then GEN
DD, then XSD.

Engine-level on purpose. Every ruleset -- SYOG26, SOLG28, whatever comes next --
inherits the same precedence, so a new pack does not have to restate it.

Why this order: the sport DD is written for one discipline and one message and
is the most specific statement available. The GEN DD covers messages a sport DD
does not define. The XSD is last because its single shared `competitionType`
applies to every message at once and so cannot express a per-message rule -- it
is a structural backstop, not an authority on obligation.
"""
from odf_validator.rules.obligations import ObligationRegistry


def reg(**kw):
    r = ObligationRegistry(xsd_required=kw.pop("xsd_required", set()))
    for disc, ob in kw.pop("disciplines", {}).items():
        r.add_discipline(disc, ob)
    if "general" in kw:
        r.set_general(kw.pop("general"))
    return r


def test_discipline_dd_beats_the_xsd():
    """The case that motivated all of this: XSD requires Competition/@Gen for
    every message; the SWM DD says optional for DT_RESULT."""
    r = reg(xsd_required={("Competition", "Gen")},
            disciplines={"SWM": {("DT_RESULT", "Competition", "Gen"): "O"}})
    assert r.resolve("SWM", "DT_RESULT", "Competition", "Gen") == "O"


def test_discipline_dd_can_also_confirm_mandatory():
    r = reg(xsd_required={("Competition", "Gen")},
            disciplines={"SWM": {("DT_ENTRIES", "Competition", "Gen"): "M"}})
    assert r.resolve("SWM", "DT_ENTRIES", "Competition", "Gen") == "M"


def test_falls_back_to_gen_dd_when_the_sport_dd_is_silent():
    """DT_PDF and DT_SCHEDULE_UPDATE are not defined in the SWM DD."""
    r = reg(xsd_required={("Competition", "Gen")},
            disciplines={"SWM": {("DT_RESULT", "Competition", "Gen"): "O"}},
            general={("DT_PDF", "Competition", "Gen"): "M"})
    assert r.resolve("SWM", "DT_PDF", "Competition", "Gen") == "M"


def test_falls_back_to_xsd_when_neither_dd_mentions_it():
    r = reg(xsd_required={("Competition", "Codes")})
    assert r.resolve("SWM", "DT_LOCAL_ON", "Competition", "Codes") == "M"


def test_unknown_attribute_has_no_obligation():
    assert reg().resolve("SWM", "DT_RESULT", "Competition", "Nonsense") is None


def test_one_discipline_does_not_leak_into_another():
    r = reg(xsd_required={("Competition", "Gen")},
            disciplines={"SWM": {("DT_RESULT", "Competition", "Gen"): "O"}})
    assert r.resolve("ARC", "DT_RESULT", "Competition", "Gen") == "M"  # XSD


def test_obligation_is_per_message_not_per_attribute():
    r = reg(disciplines={"SWM": {("DT_ENTRIES", "Competition", "Gen"): "M",
                                 ("DT_RESULT", "Competition", "Gen"): "O"}})
    assert r.resolve("SWM", "DT_ENTRIES", "Competition", "Gen") == "M"
    assert r.resolve("SWM", "DT_RESULT", "Competition", "Gen") == "O"


def test_obligation_is_per_element_not_per_attribute_name():
    """`Code` is required on 83 complexTypes; an obligation on one element must
    not answer for another."""
    r = reg(xsd_required={("MedalLine", "Rank")},
            disciplines={"SWM": {("DT_RESULT", "Result", "Rank"): "O"}})
    assert r.resolve("SWM", "DT_RESULT", "Result", "Rank") == "O"
    assert r.resolve("SWM", "DT_RESULT", "MedalLine", "Rank") == "M"


def test_mandatory_attrs_lists_what_a_message_must_carry():
    r = reg(disciplines={"SWM": {("DT_RESULT", "Result", "SortOrder"): "M",
                                 ("DT_RESULT", "Result", "Rank"): "O",
                                 ("DT_ENTRIES", "Entry", "Code"): "M"}})
    assert r.mandatory_attrs("SWM", "DT_RESULT") == {("Result", "SortOrder")}


def test_mandatory_attrs_merges_gen_dd_without_overriding_the_sport_dd():
    r = reg(disciplines={"SWM": {("DT_RESULT", "Result", "Rank"): "O"}},
            general={("DT_RESULT", "Result", "Rank"): "M",
                     ("DT_RESULT", "Competition", "Sport"): "M"})
    got = r.mandatory_attrs("SWM", "DT_RESULT")
    assert ("Competition", "Sport") in got
    assert ("Result", "Rank") not in got


def test_declared_attrs_filter_drops_impossible_rows():
    """Converted-PDF parsing mis-attributes some attributes to the wrong
    element. Where the schema declares no such attribute on that element the
    row cannot be right, so it is discarded instead of being trusted."""
    r = ObligationRegistry(xsd_declared={("Competition", "Gen"),
                                         ("Team", "Code")})
    r.add_discipline("ARC", {("DT_PARTIC", "Team", "Gen"): "O",
                             ("DT_PARTIC", "Team", "Code"): "O"})
    assert r.resolve("ARC", "DT_PARTIC", "Team", "Code") == "O"
    assert r.resolve("ARC", "DT_PARTIC", "Team", "Gen") is None


def test_filter_is_inert_when_the_schema_is_unknown():
    """No declared-attribute information means no filtering; a pack without a
    compiling XSD must not silently lose every obligation."""
    r = ObligationRegistry()
    r.add_discipline("ARC", {("DT_PARTIC", "Team", "Gen"): "O"})
    assert r.resolve("ARC", "DT_PARTIC", "Team", "Gen") == "O"


def test_full_rsc_discipline_code_resolves_like_the_short_one():
    """dispatch() reports Competition/Discipline/@Code verbatim, which in ODF
    is a 34-character RSC. Obligations must not depend on which spelling a
    message happens to carry."""
    r = reg(disciplines={"SWM": {("DT_RESULT", "Competition", "Gen"): "O"}})
    assert r.resolve("SWM" + "-" * 31, "DT_RESULT", "Competition", "Gen") == "O"
    assert r.resolve("SWM", "DT_RESULT", "Competition", "Gen") == "O"


# ---------------- enforceable subset ----------------
# Suppressing a finding the DD excuses is low-risk: at worst one error is
# hidden. ENFORCING a mandatory attribute is not: a wrong obligation fires on
# every matching element in every file. Measured on the real 2026-06-05 corpus,
# two mis-attributed rows would have produced 38,648 findings.
#
# So enforcement is restricted to pairs where two independent things hold:
#   1. the element name maps to exactly one complexType -- <Description> is 13
#      different types, so a team-only @TeamName obligation would otherwise leak
#      onto every athlete, coach and official description (5,419 findings on the
#      real corpus, all bogus);
#   2. the attribute is declared on exactly one element in the schema, so a
#      mis-attribution by the DD parser lands on an element that does not have
#      it and is caught by the declared-attribute filter.


def test_enforceable_requires_an_unambiguous_element_and_attribute():
    r = ObligationRegistry(xsd_declared={("Competition", "Gen")},
                           xsd_unambiguous={("Competition", "Gen")})
    r.add_discipline("SWM", {("DT_ENTRIES", "Competition", "Gen"): "M"})
    assert r.mandatory_attrs("SWM", "DT_ENTRIES", enforceable_only=True) == {
        ("Competition", "Gen")}


def test_ambiguous_pairs_are_excluded_from_enforcement():
    """Description/@TeamName: the element name covers 13 complexTypes."""
    r = ObligationRegistry(xsd_declared={("Description", "TeamName")},
                           xsd_unambiguous=set())
    r.add_discipline("SWM", {("DT_RESULT", "Description", "TeamName"): "M"})
    assert r.mandatory_attrs("SWM", "DT_RESULT", enforceable_only=True) == set()
    # still reported when not filtering, so the data is not lost
    assert r.mandatory_attrs("SWM", "DT_RESULT") == {("Description", "TeamName")}


def test_enforcement_respects_a_discipline_saying_optional():
    """ExtendedResult/@Value2 is M for WST and O for SWM."""
    r = ObligationRegistry(xsd_declared={("ExtendedResult", "Value2")},
                           xsd_unambiguous={("ExtendedResult", "Value2")})
    r.add_discipline("WST", {("DT_RESULT", "ExtendedResult", "Value2"): "M"})
    r.add_discipline("SWM", {("DT_RESULT", "ExtendedResult", "Value2"): "O"})
    assert r.mandatory_attrs("WST", "DT_RESULT", enforceable_only=True)
    assert not r.mandatory_attrs("SWM", "DT_RESULT", enforceable_only=True)


def test_no_schema_information_means_nothing_is_enforceable():
    """Fail closed: without the schema we cannot prove a pair is unambiguous,
    and guessing would reintroduce exactly the risk this guard exists for."""
    r = ObligationRegistry()
    r.add_discipline("SWM", {("DT_ENTRIES", "Competition", "Gen"): "M"})
    assert r.mandatory_attrs("SWM", "DT_ENTRIES", enforceable_only=True) == set()


def test_enforcement_skips_what_the_xsd_already_reports():
    """Otherwise every missing Competition/@Gen in a DT_ENTRIES message yields
    two errors for one defect -- XSD_INVALID and CORE_DD_MANDATORY_ATTR. On the
    real corpus that doubled the error count from 539 to 1,062 with no new
    information. Enforcement exists to cover the gap the schema leaves, so
    anything the schema already requires is the schema's to report."""
    r = ObligationRegistry(xsd_required={("Competition", "Gen")},
                           xsd_declared={("Competition", "Gen"),
                                         ("Progress", "LastUnit")},
                           xsd_unambiguous={("Competition", "Gen"),
                                            ("Progress", "LastUnit")})
    r.add_discipline("SWM", {("DT_ENTRIES", "Competition", "Gen"): "M",
                             ("DT_ENTRIES", "Progress", "LastUnit"): "M"})
    got = r.mandatory_attrs("SWM", "DT_ENTRIES", enforceable_only=True)
    assert got == {("Progress", "LastUnit")}
    # unfiltered still reports both, so the obligation data stays intact
    assert len(r.mandatory_attrs("SWM", "DT_ENTRIES")) == 2
