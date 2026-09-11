from __future__ import annotations
from pathlib import Path

import pytest

from odf_validator.ingestion.convert import ConversionError, dd_to_markdown


class _Boom:
    """A converter that fails the way a missing wheel or an unparseable PDF
    does."""
    def convert(self, path):
        raise RuntimeError("pdf-inspector unavailable")


class _NotAnException(BaseException):
    """The shape of the two exceptions this module's real backends raise.

    markitdown's FileConversionException has __mro__ (cls, BaseException,
    object), and pdf-inspector is a Rust/PyO3 extension whose panics arrive as
    pyo3_runtime.PanicException, likewise a BaseException. Neither is caught by
    `except Exception`, which is how a corrupt Data Dictionary once escaped
    build_ruleset_pack() and 500'd POST /sources/apply.

    Declared locally and deriving from BaseException on purpose: this pins the
    behaviour WITHOUT needing either optional wheel installed. The one existing
    test that exercises a real BaseException here is gated on an importorskip
    for pdf_inspector, so on a machine without that wheel the guard could be
    reverted to `except Exception` and the whole suite would still pass.
    """


class _Panics:
    def convert(self, path):
        raise _NotAnException("a panic crossing the extension boundary")


class _ReturnsNothing:
    """markitdown on a scanned, image-only PDF: it does not raise, it returns
    normally with empty text."""
    def convert(self, path):
        class _R:
            text_content = ""
        return _R()


class _Works:
    def __init__(self, text):
        self.text = text

    def convert(self, path):
        class _R:
            text_content = self.text
        return _R()


def test_a_pdf_falls_back_to_markitdown_when_the_primary_fails(tmp_path,
                                                               monkeypatch):
    """A contributor whose platform has no pdf-inspector wheel should still
    get a converted Data Dictionary rather than nothing."""
    pdf = tmp_path / "ODF_SWM_Data_Dictionary.pdf"
    pdf.write_bytes(b"%PDF-1.7")

    import odf_validator.ingestion.convert as convert_module
    monkeypatch.setattr(convert_module, "PdfInspectorConverter",
                        lambda: _Boom())
    monkeypatch.setattr(convert_module, "_markitdown_converter",
                        lambda: _Works("# fallback markdown"))

    markdown, backend = dd_to_markdown(pdf)

    assert markdown == "# fallback markdown"
    assert backend == "markitdown"


def test_the_primary_backend_is_reported_when_it_succeeds(tmp_path,
                                                          monkeypatch):
    pdf = tmp_path / "ODF_SWM_Data_Dictionary.pdf"
    pdf.write_bytes(b"%PDF-1.7")

    import odf_validator.ingestion.convert as convert_module
    monkeypatch.setattr(convert_module, "PdfInspectorConverter",
                        lambda: _Works("# primary markdown"))

    markdown, backend = dd_to_markdown(pdf)

    assert markdown == "# primary markdown"
    assert backend == "pdf-inspector"


def test_both_backends_failing_still_raises(tmp_path, monkeypatch):
    """A fallback is not a licence to swallow the failure -- if neither
    backend works the caller must hear about it."""
    pdf = tmp_path / "ODF_SWM_Data_Dictionary.pdf"
    pdf.write_bytes(b"%PDF-1.7")

    import odf_validator.ingestion.convert as convert_module
    monkeypatch.setattr(convert_module, "PdfInspectorConverter",
                        lambda: _Boom())
    monkeypatch.setattr(convert_module, "_markitdown_converter",
                        lambda: _Boom())

    # ConversionError specifically, not bare Exception: the point is that the
    # failure is CATCHABLE by builder.py's `except Exception`. A bare Exception
    # here would also pass for a BaseException leaking through, which is the
    # bug this file now guards.
    with pytest.raises(ConversionError):
        dd_to_markdown(pdf)


def test_a_baseexception_from_either_backend_becomes_a_conversion_error(
        tmp_path, monkeypatch):
    """Neither backend may leak a BaseException past build_ruleset_pack.

    Runs on any machine -- no pdf_inspector or markitdown wheel needed -- so it
    still fails if either `except BaseException` in convert.py is narrowed back
    to `except Exception`.
    """
    pdf = tmp_path / "ODF_SWM_Data_Dictionary.pdf"
    pdf.write_bytes(b"%PDF-1.7")

    import odf_validator.ingestion.convert as convert_module
    monkeypatch.setattr(convert_module, "PdfInspectorConverter",
                        lambda: _Panics())
    monkeypatch.setattr(convert_module, "_markitdown_converter",
                        lambda: _Panics())

    with pytest.raises(ConversionError):
        dd_to_markdown(pdf)


def test_a_fallback_that_extracts_nothing_is_an_error_not_empty_markdown(
        tmp_path, monkeypatch):
    """The scanned-DD path. pdf-inspector rejects an image-only document with a
    loud "needs OCR" ConversionError; markitdown then returns "" instead of
    raising. If the fallback accepted that, build_ruleset_pack would parse ""
    into {} and write it to the committed obligation cache as the document's
    real obligations -- a silent, restart-surviving degradation, and exactly
    the "DD with no rules in it" outcome ConversionError exists to prevent.
    """
    pdf = tmp_path / "ODF_SWM_Data_Dictionary.pdf"
    pdf.write_bytes(b"%PDF-1.7")

    import odf_validator.ingestion.convert as convert_module
    monkeypatch.setattr(convert_module, "PdfInspectorConverter",
                        lambda: _Boom())
    monkeypatch.setattr(convert_module, "_markitdown_converter",
                        lambda: _ReturnsNothing())

    with pytest.raises(ConversionError, match="no text"):
        dd_to_markdown(pdf)


def test_markdown_passthrough_reports_its_own_backend(tmp_path):
    md = tmp_path / "ODF_ARC_Data_Dictionary.md"
    md.write_text("# already markdown", encoding="utf-8")

    markdown, backend = dd_to_markdown(md)

    assert markdown == "# already markdown"
    assert backend == "passthrough"
