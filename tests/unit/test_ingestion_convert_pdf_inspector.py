"""Converter migration guard: markitdown -> pdf-inspector for PDFs (2026-08-06).

Two things are pinned here:
  1. Routing. .pdf must go to pdf-inspector, .docx must stay on markitdown
     (pdf-inspector is PDF-only), .md stays a passthrough.
  2. Rule-extraction parity. The swap must not change which draft rules the
     DD parser pulls out of the real Data Dictionaries -- that is the only
     property of the conversion the ruleset actually depends on.

Baselines are the counts measured across all 24 SYOG26 DD PDFs.
"""
from pathlib import Path

import pytest

from odf_validator.ingestion.convert import (
    ConversionError,
    PdfInspectorConverter,
    _markitdown_converter,
    dd_to_markdown,
)
from odf_validator.ingestion.dd_parser import extract_draft_rules

DISCIPLINES = Path("Rules/SYOG26/Disciplines")

# Rule counts per discipline, verified identical between markitdown and
# pdf-inspector except TRI (see test_tri_location_is_the_one_known_divergence).
EXPECTED_RULE_COUNTS = {
    "ATH": 17, "BDM": 17, "BK3": 19, "BKG": 18, "BOX": 16, "BS5": 17,
    "CRD": 12, "EQU": 12, "FBS": 17, "FEN": 17, "GAR": 13, "HBB": 18,
    "JUD": 17, "RCB": 14, "RU7": 18, "SAL": 14, "SKB": 12, "SWM": 14,
    "TKW": 17, "TRI": 11, "TTE": 15, "VBV": 18, "WRB": 18, "WST": 12,
}


def _dd_pdf(discipline: str) -> Path:
    return DISCIPLINES / discipline / f"ODF_{discipline}_Data_Dictionary.pdf"


@pytest.fixture
def real_pdf_inspector():
    """Skip guard, deliberately narrow.

    A previous version of this file called pytest.importorskip("pdf_inspector")
    at module level, which skipped all 32 tests here as one block whenever the
    optional pdf-inspector wheel wasn't installed -- including 5 tests that
    never touch the real package (they exercise converter *routing* and the
    converter-injection seam using fakes/monkeypatched sys.modules). That
    silently stopped those 5 from ever running in this environment. Only the
    tests below that request this fixture actually need the real package
    installed; the rest run unconditionally.
    """
    pytest.importorskip(
        "pdf_inspector",
        reason="optional DD converter (requirements.txt); absent in this environment",
    )


# --- routing ---------------------------------------------------------------

def test_pdf_routes_to_pdf_inspector(tmp_path, monkeypatch):
    """A .pdf must reach pdf-inspector first. The markitdown fallback only
    exists for when that attempt fails, so a successful conversion must never
    report any other backend."""
    import odf_validator.ingestion.convert as convert_module

    class _Spy(PdfInspectorConverter):
        def convert(self, path):
            return type("R", (), {"text_content": "from pdf-inspector"})()

    monkeypatch.setattr(convert_module, "PdfInspectorConverter", _Spy)
    p = tmp_path / "dd.pdf"
    p.write_bytes(b"%PDF-1.4 stub")
    assert dd_to_markdown(p) == ("from pdf-inspector", "pdf-inspector")


def test_docx_still_routes_to_markitdown():
    # pdf-inspector is PDF-only, so markitdown remains the .docx backend.
    conv = _markitdown_converter()
    assert not isinstance(conv, PdfInspectorConverter)
    assert type(conv).__name__ == "MarkItDown"


def test_markdown_source_never_touches_a_converter(tmp_path):
    p = tmp_path / "dd.md"
    p.write_text("Venue M CC@VENUE Venue where the session takes place")
    assert dd_to_markdown(p) == (
        "Venue M CC@VENUE Venue where the session takes place", "passthrough")


def test_injected_converter_still_wins_over_the_default(tmp_path):
    """The converter= seam builder.py and the older tests rely on must keep
    overriding backend selection, so unit tests never need a real PDF."""
    class _Fake:
        def __init__(self):
            self.calls = []

        def convert(self, path):
            self.calls.append(path)
            return type("R", (), {"text_content": "injected"})()

    p = tmp_path / "dd.pdf"
    p.write_bytes(b"%PDF-1.4 stub")
    fake = _Fake()
    assert dd_to_markdown(p, converter=fake) == ("injected", "explicit")
    assert fake.calls == [str(p)]


@pytest.mark.usefixtures("real_pdf_inspector")
def test_malformed_pdf_raises_instead_of_returning_empty_text(tmp_path):
    """build_ruleset_pack() catches this and records an ingestion error; the
    failure mode to avoid is a DD that quietly converts to nothing.

    Unlike the other tests above, no converter is injected here, so
    dd_to_markdown() reaches PdfInspectorConverter.convert(), which does
    `import pdf_inspector` unconditionally -- this needs the real package.

    ConversionError, not the raw ValueError pdf-inspector raises: both
    backends fail on this stub, and markitdown's FileConversionException
    derives from BaseException, so letting it through meant `except Exception`
    in builder.py could not catch it and POST /sources/apply 500'd. The
    `match` keeps the other half of the contract -- the useful diagnosis has
    to survive the fallback, not be replaced by markitdown's wrapped
    traceback."""
    p = tmp_path / "dd.pdf"
    p.write_bytes(b"%PDF-1.4 stub")
    with pytest.raises(ConversionError, match="Not a PDF"):
        dd_to_markdown(p)


def test_scanned_pdf_raises_conversion_error_naming_the_ocr_gap(monkeypatch):
    """A structurally valid but image-only DD extracts no text. That must be a
    loud error mentioning OCR, not a DD that looks like it has zero rules."""
    import sys
    import types

    fake_result = types.SimpleNamespace(
        markdown="", pdf_type="scanned", confidence=0.98, pages_needing_ocr=[1, 2])
    fake_module = types.SimpleNamespace(process_pdf=lambda _p: fake_result)
    monkeypatch.setitem(sys.modules, "pdf_inspector", fake_module)

    with pytest.raises(ConversionError) as exc:
        PdfInspectorConverter().convert("scanned_dd.pdf")
    message = str(exc.value)
    assert "scanned_dd.pdf" in message
    assert "scanned" in message and "OCR" in message


# --- real Data Dictionary parity ------------------------------------------

@pytest.mark.usefixtures("real_pdf_inspector")
@pytest.mark.parametrize("discipline", sorted(EXPECTED_RULE_COUNTS))
def test_each_dd_converts_and_yields_the_expected_draft_rules(discipline):
    pdf = _dd_pdf(discipline)
    if not pdf.exists():
        pytest.skip(f"{pdf} not present")
    markdown, _backend = dd_to_markdown(pdf)
    drafts = extract_draft_rules(markdown, discipline, pdf.name)
    assert len(drafts) == EXPECTED_RULE_COUNTS[discipline], (
        f"{discipline}: extracted {sorted(d.id for d in drafts)}")


@pytest.mark.usefixtures("real_pdf_inspector")
def test_all_dds_classify_as_text_based_with_no_encoding_issues():
    """If a re-supplied DD ever arrives as a scan, this fails loudly instead of
    quietly producing an empty ruleset."""
    pdfs = sorted(DISCIPLINES.glob("*/ODF_*_Data_Dictionary.pdf"))
    if not pdfs:
        pytest.skip("no DD PDFs present")
    converter = PdfInspectorConverter()
    for pdf in pdfs:
        result = converter.convert(str(pdf)).source
        assert result.pdf_type == "text_based", f"{pdf.name}: {result.pdf_type}"
        assert not result.has_encoding_issues, f"{pdf.name} has encoding issues"


@pytest.mark.usefixtures("real_pdf_inspector")
def test_tri_location_is_the_one_known_divergence():
    """Documents the single accepted regression of the markitdown swap.

    pdf-inspector scrambles the column order of TRI's Location row
    (`|Location||M||Id|CC@LOCATION|`), so _CC_LINE no longer matches it and
    TRI_LOCATION_CODE is not re-drafted. The rule already exists hand-curated
    and active in the TRI pack, so the shipped ruleset is unaffected -- but if
    the TRI DD is ever re-supplied and re-ingested, it will not come back on
    its own. If this test starts failing because the id IS present again,
    pdf-inspector has improved: delete this test and bump TRI to 12.
    """
    pdf = _dd_pdf("TRI")
    if not pdf.exists():
        pytest.skip(f"{pdf} not present")
    ids = {d.id for d in extract_draft_rules(dd_to_markdown(pdf)[0], "TRI",
                                             pdf.name)}
    assert "TRI_LOCATION_CODE" not in ids

    curated = Path("Rules/SYOG26/Disciplines/TRI/rules/ODF_TRI_Data_Dictionary.pdf.yaml")
    assert "TRI_LOCATION_CODE" in curated.read_text(encoding="utf-8"), (
        "TRI_LOCATION_CODE is no longer curated in the TRI pack and is no "
        "longer auto-extracted either -- the Location check would be lost")
