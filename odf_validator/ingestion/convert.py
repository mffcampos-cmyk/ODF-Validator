from __future__ import annotations
import asyncio
from pathlib import Path

_PASSTHROUGH_SUFFIXES = {".md", ".markdown"}
_PDF_SUFFIXES = {".pdf"}


class ConversionError(RuntimeError):
    """A Data Dictionary source could not be turned into usable Markdown.

    Raised instead of returning empty text so build_ruleset_pack() reports the
    DD as a loud ingestion error rather than silently extracting zero rules
    from it (a scanned DD would otherwise look like a DD with no rules in it).
    """


class _Converted:
    """markitdown-shaped result (`.text_content`) so both converter backends
    present the same duck-type to dd_to_markdown() and to tests that inject a
    fake converter."""

    def __init__(self, text_content: str, source=None):
        self.text_content = text_content
        # Classification metadata from pdf-inspector (pdf_type, confidence,
        # pages_needing_ocr, has_encoding_issues, pages_with_tables...). Not
        # used by the current line-regex parser; kept so a future table-aware
        # parser or an ingestion health check can reach it without re-parsing.
        self.source = source


class PdfInspectorConverter:
    """PDF -> Markdown via firecrawl/pdf-inspector (Rust, PyO3 bindings).

    Replaces markitdown for PDFs. Measured over all 24 SYOG26 Data Dictionary
    PDFs: ~27x faster
    (10.6s vs ~290s for the set), identical extracted rule-id sets for 23 of
    24 disciplines, and structurally better Markdown -- real tables with cell
    boundaries, heading levels, unwrapped paragraphs, and repeated page
    headers/footers dropped.

    KNOWN DIVERGENCE (TRI): ragged/merged table cells at a section boundary can
    scramble column order, e.g. `|Location||M||Id|CC@LOCATION|`, which
    dd_parser._CC_LINE won't match (an `Id` token lands between the M/O flag
    and CC@). That costs TRI_LOCATION_CODE on re-ingest; the rule already
    exists hand-curated and active in the TRI pack, so the shipped ruleset is
    unaffected. See tests/unit/test_ingestion_convert_pdf_inspector.py.
    """

    def convert(self, path):
        import pdf_inspector

        result = pdf_inspector.process_pdf(str(path))
        markdown = result.markdown
        if not markdown or not markdown.strip():
            raise ConversionError(
                f"{Path(path).name}: no extractable text "
                f"(pdf_type={result.pdf_type!r}, confidence={result.confidence:.2f}, "
                f"pages_needing_ocr={result.pages_needing_ocr}). "
                "A scanned/image-only Data Dictionary needs OCR before ingestion."
            )
        return _Converted(markdown, source=result)


def _markitdown_converter():
    """markitdown, imported lazily so a PDF-only install never pays for it."""
    from markitdown import MarkItDown
    return MarkItDown()


# Control-flow exceptions that must never be turned into an ingestion error.
# CancelledError is a BaseException too (since 3.8) and would otherwise be
# swallowed if conversion ever moves onto an async path.
_NEVER_SWALLOW = (KeyboardInterrupt, SystemExit, GeneratorExit,
                  asyncio.CancelledError)


def _markitdown_text(path) -> str:
    """markitdown's extracted text, with its BaseException normalised.

    markitdown signals a failed conversion with FileConversionException, which
    in the pinned version derives from BaseException, NOT Exception:

        >>> FileConversionException.__mro__
        (<class '...FileConversionException'>, <class 'BaseException'>, ...)

    Every `except Exception` in ingestion/builder.py therefore failed to catch
    it. One corrupt or truncated PDF escaped build_ruleset_pack entirely and
    turned POST /sources/apply into a 500 (plus Starlette's "No response
    returned.") instead of being recorded in report.dd_unconvertible -- which
    is the whole reason dd_unconvertible exists. On a real first launch that
    is a half-finished download crashing the import rather than reporting one
    bad document.

    Re-raising as ConversionError keeps the documented contract intact -- a
    conversion that did not happen still propagates and never returns empty
    text -- while making it catchable by ordinary handlers. The three control
    -flow exceptions are re-raised untouched; swallowing a Ctrl-C into an
    ingestion error would be its own bug.
    """
    try:
        text = _markitdown_converter().convert(str(path)).text_content
    except _NEVER_SWALLOW:
        raise
    except BaseException as exc:
        raise ConversionError(f"markitdown failed: {exc}") from exc
    # markitdown does NOT raise on a scanned/image-only PDF -- it returns
    # normally with empty text_content. Without this check the fallback would
    # swallow pdf-inspector's loud "needs OCR" diagnosis and hand back "",
    # which build_ruleset_pack then parses into {} and WRITES to the committed
    # obligation cache as that document's legitimate obligation set. The
    # degradation would survive restarts. That is the precise failure
    # ConversionError exists to prevent, so the fallback must honour the same
    # contract as the primary backend rather than quietly undercutting it.
    if not text or not text.strip():
        raise ConversionError("markitdown extracted no text (an image-only "
                              "document needs OCR before ingestion)")
    return text


def dd_to_markdown(path: Path, converter=None) -> tuple[str, str]:
    """Convert a Data Dictionary source file to Markdown.

    Returns (markdown, backend) where backend is 'pdf-inspector',
    'markitdown', 'passthrough' or 'explicit' (a converter injected by the
    caller, which is what tests and build_ruleset_pack()'s seam use).

    .md/.markdown files are already Markdown and are read as-is, no converter
    needed. .pdf goes to pdf-inspector first and falls back to markitdown if
    that fails -- a missing wheel for the running platform, or a PDF it cannot
    process. .docx goes straight to markitdown, which pdf-inspector cannot
    replace (it is PDF-only).

    The backend is RETURNED rather than swallowed because dd_parser's line
    regexes are tuned to pdf-inspector's Markdown shape (hence the pin in
    requirements.txt); markitdown's output differs, so a caller needs to know
    a fallback happened before trusting the obligations parsed out of it.

    If both backends fail the error propagates: a fallback is not a licence
    to hide a conversion that did not happen.
    """
    suffix = path.suffix.lower()
    if suffix in _PASSTHROUGH_SUFFIXES:
        return path.read_text(encoding="utf-8"), "passthrough"

    if converter is not None:
        return converter.convert(str(path)).text_content, "explicit"

    if suffix in _PDF_SUFFIXES:
        try:
            result = PdfInspectorConverter().convert(str(path))
            return result.text_content, "pdf-inspector"
        except _NEVER_SWALLOW:
            raise
        # BaseException, not Exception. pdf-inspector is a Rust/PyO3 extension,
        # and a Rust panic crossing the PyO3 boundary arrives as
        # pyo3_runtime.PanicException -- which, exactly like markitdown's
        # FileConversionException, derives from BaseException. Catching only
        # Exception here would let a panic skip the fallback AND both
        # `except Exception` handlers in builder.py, reproducing the very 500
        # on /sources/apply that this whole error path exists to prevent --
        # just on the other backend. Defending the fallback while leaving the
        # primary open would have been the worse half to fix: this is the
        # branch that runs on every PDF.
        except BaseException as primary:
            try:
                return _markitdown_text(path), "markitdown"
            except ConversionError as fallback:
                # Lead with pdf-inspector's reason. It is the specific one
                # ("Not a PDF: invalid PDF file header"); markitdown's is a
                # formatted traceback that buries the diagnosis.
                raise ConversionError(
                    f"{path.name}: pdf-inspector failed ({primary}) and the "
                    f"markitdown fallback also failed ({fallback})"
                ) from primary

    return _markitdown_text(path), "markitdown"
