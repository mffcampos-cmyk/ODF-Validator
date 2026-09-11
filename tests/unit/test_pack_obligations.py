"""build_ruleset_pack exposes the DD obligations the validator will honour.

Two properties matter beyond "it parses":

1. Obligations must be complete on EVERY pack load. The existing DD loop skips
   files whose hash is unchanged, because its job is suggesting draft rules and
   re-suggesting them is pointless. Obligations are different: skipping an
   unchanged DD would mean the second load of a pack silently validates against
   fewer obligations than the first.
2. Converting 24 PDFs costs ~12s, and discover_packs() runs at import, so the
   result has to be cached and only recomputed for DDs that actually changed.
"""
from pathlib import Path

from odf_validator.ingestion.builder import build_ruleset_pack
from tests.conftest import needs_populated_ruleset

PACK_DIR = Path("Rules/SYOG26")


def test_pack_carries_an_obligation_registry():
    pack = build_ruleset_pack(PACK_DIR)
    assert pack.obligations is not None


@needs_populated_ruleset
def test_swm_gen_is_optional_for_results_and_mandatory_for_entries():
    """The finding that started this: same attribute, two obligations."""
    r = build_ruleset_pack(PACK_DIR).obligations
    assert r.resolve("SWM", "DT_RESULT", "Competition", "Gen") == "O"
    assert r.resolve("SWM", "DT_ENTRIES", "Competition", "Gen") == "M"


@needs_populated_ruleset
def test_every_discipline_agrees_about_gen():
    """All 25 SYOG26 DDs mark Gen mandatory for DT_ENTRIES only."""
    r = build_ruleset_pack(PACK_DIR).obligations
    discs = [d for d in r.disciplines() if d]
    assert len(discs) >= 24
    for d in discs:
        assert r.resolve(d, "DT_ENTRIES", "Competition", "Gen") == "M", d


@needs_populated_ruleset
def test_message_absent_from_the_sport_dd_falls_back_to_mandatory():
    """DT_PDF is not defined in the SWM DD, so the obligation must not be
    downgraded to optional just because SWM is silent.

    Needs the imported ruleset: with no DD ruling on the key, resolve() only
    reaches "M" through the compiled XSD (obligations.py, the self._xsd
    branch). An empty registry answers None -- "unknown", not "optional" --
    which is correct behaviour, so this asserts nothing until the first-launch
    import has produced Rules/SYOG26/xsd/.
    """
    r = build_ruleset_pack(PACK_DIR).obligations
    assert r.resolve("SWM", "DT_PDF", "Competition", "Gen") == "M"


def test_obligations_survive_a_second_load_from_cache():
    first = build_ruleset_pack(PACK_DIR).obligations
    second = build_ruleset_pack(PACK_DIR).obligations
    for dt in ("DT_RESULT", "DT_ENTRIES", "DT_PDF"):
        assert (first.resolve("SWM", dt, "Competition", "Gen")
                == second.resolve("SWM", dt, "Competition", "Gen")), dt


@needs_populated_ruleset
def test_obligations_the_schema_says_cannot_exist_are_discarded():
    """A DD table interrupted by a nested element's table makes document order
    an unreliable guide to which element an attribute belongs to. Where the XSD
    can prove the attribute is not declared on that element, drop the row rather
    than trust the parse -- 279 such rows across the SYOG26 DDs.

    This does not catch every mis-attribution (Result and ExtendedResult both
    declare @SortOrder, so swapping them is invisible here), which is why
    enforcement of DD-mandatory attributes is not switched on yet."""
    r = build_ruleset_pack(PACK_DIR).obligations
    swm = r._disciplines["SWM"]
    assert ("DT_PARTIC", "Team", "Gen") not in swm
    assert r.resolve("SWM", "DT_RESULT", "Competition", "Gen") == "O"


def test_the_obligation_cache_is_not_reported_as_a_stray_file():
    """The cache lives inside the ruleset directory, so the scanner has to know
    about it -- otherwise every pack load reports it as an unrecognised file
    and the pack looks broken."""
    pack = build_ruleset_pack(PACK_DIR)
    assert not [e for e in pack.report.errors if "dd_obligations" in e]
