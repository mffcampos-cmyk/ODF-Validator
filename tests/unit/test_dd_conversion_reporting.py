"""A Data Dictionary that will not convert is not a rule that failed to load.

Reported 2026-08-14: opening the app showed "24 rule(s) failed to load — first:
Failed to convert Data Dictionary ODF_ATH_Data_Dictionary.pdf: No module named
'pdf_inspector'", alongside "98 rules active". No rule failed to load; all 98
loaded. `app.js` renders anything in `report.errors` with that wording, and DD
conversion failures were being appended there.

The distinction matters because the two have different consequences. A rule
that fails to load is a broken ruleset. A DD that fails to convert leaves the
ruleset intact and costs only the obligations for that DD -- which, now the
obligation cache is committed, is usually nothing at all.
"""
from pathlib import Path

from odf_validator.ingestion.builder import build_ruleset_pack, _note_fallback
from odf_validator.loader.pack import LoadReport

PACK_DIR = Path("Rules/SYOG26")


def test_report_has_a_channel_for_unconvertible_dds():
    assert hasattr(LoadReport(), "dd_unconvertible")


def test_a_fallback_conversion_is_reported_without_being_called_a_failure():
    """The other half of the same distinction: a DD that converted, but by
    the fallback backend, is neither a failure nor a non-event.

    Its rules loaded, so it must stay off `errors`. But the obligation
    regexes are tuned to the primary backend's Markdown shape, so an
    operator has to be told before trusting what was parsed out of it --
    a silent fallback is the failure mode this channel exists to prevent.
    """
    report = LoadReport()
    _note_fallback(report, Path("ODF_SWM_Data_Dictionary.pdf"), "markitdown")
    assert len(report.converted_by_fallback) == 1
    assert "ODF_SWM_Data_Dictionary.pdf" in report.converted_by_fallback[0]
    assert report.errors == []

    # A DD converted twice in one load (obligations, then draft suggestions)
    # is one fact, not two.
    _note_fallback(report, Path("ODF_SWM_Data_Dictionary.pdf"), "markitdown")
    assert len(report.converted_by_fallback) == 1

    # The primary backend, and .docx -- which has no primary to fall back
    # FROM -- are both silent.
    _note_fallback(report, Path("ODF_ATH_Data_Dictionary.pdf"), "pdf-inspector")
    _note_fallback(report, Path("ODF_ATH_Data_Dictionary.docx"), "markitdown")
    assert len(report.converted_by_fallback) == 1


def test_conversion_failure_does_not_land_in_errors():
    def explode(path):
        raise RuntimeError("No module named 'pdf_inspector'")

    class Boom:
        def convert(self, path):
            raise RuntimeError("No module named 'pdf_inspector'")

    pack = build_ruleset_pack(PACK_DIR, converter=Boom())
    rule_load_errors = [e for e in pack.report.errors if "convert" in e.lower()]
    assert rule_load_errors == [], rule_load_errors


def test_conversion_failure_is_still_reported_somewhere():
    class Boom:
        def convert(self, path):
            raise RuntimeError("No module named 'pdf_inspector'")

    pack = build_ruleset_pack(PACK_DIR, converter=Boom())
    # The committed cache means obligations are already known, so a broken
    # converter may legitimately be a no-op. Whatever is reported must at least
    # not be miscounted as a rule-load failure.
    assert isinstance(pack.report.dd_unconvertible, list)


def test_rules_still_load_when_a_dd_cannot_be_converted():
    class Boom:
        def convert(self, path):
            raise RuntimeError("No module named 'pdf_inspector'")

    pack = build_ruleset_pack(PACK_DIR, converter=Boom())
    # 98 before the rules review that followed (still 98 immediately before it,
    # 2026-08-30), +3 from that audit:
    #   - SAL_PROTEST_SIGNEDBY_FUNCTION_CODE (item3b): a new rule id that
    #     restores Protest/SignedBy/@Function coverage SAL_FUNCTION_CODE's
    #     tag-level exclude_tags cannot express on its own.
    #   - SAL_FUNCTION_CODE itself (item3b): now differs from GEN_FUNCTION_CODE
    #     in params (it also excludes SignedBy, which GEN does not, and both
    #     now exclude Presenter -- see GEN_FUNCTION_CODE/all 20 other
    #     discipline *_FUNCTION_CODE copies, kept in lockstep so they still
    #     dedup into GEN), so SAL_FUNCTION_CODE survives semantic dedup as a
    #     specialisation instead of being silently merged into GEN's copy the
    #     way it was when the two were byte-identical.
    #   - ATH_POS_POSINT_IMAGE (item6): a new rule id that restores Image/@Pos
    #     coverage ATH_POS_POSINT dropped when it was narrowed via
    #     context_attr/context_values to only the @Code values the ATH DD
    #     documents as numeric (Image has no @Code sibling to match against).
    # 101 after the 2026-08-30 scoping work. Then 89, once the discipline
    # *_SUBEVENTNAME_CODE rules were corrected to compare against
    # ENG_shortDescription (raised by an external review): twelve of the thirteen
    # became byte-identical to GEN_SUBEVENTNAME_CODE and semantic dedup
    # absorbed them, so the check runs under the GEN rule id. SWM is the
    # exception -- it keeps ENG_Description by owner decision (2026-09-01),
    # so its rule still differs and survives as a genuine specialisation.
    #
    # A DROP here is expected only when rules become identical to a generic
    # one. If this number falls for any other reason, coverage has been lost.
    assert len(pack.rules) == 89
