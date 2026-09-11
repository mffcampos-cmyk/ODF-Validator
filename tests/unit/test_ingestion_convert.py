from pathlib import Path
from odf_validator.ingestion.convert import dd_to_markdown


class _FakeResult:
    def __init__(self, text):
        self.text_content = text


class _FakeConverter:
    def __init__(self, text):
        self._text = text
        self.calls = []

    def convert(self, path):
        self.calls.append(path)
        return _FakeResult(self._text)


def test_markdown_source_is_passed_through_without_a_converter(tmp_path):
    p = tmp_path / "dd.md"
    p.write_text("Venue M CC@VENUE Venue where the session takes place")
    # No converter given: .md must not require markitdown at all.
    assert dd_to_markdown(p) == (
        "Venue M CC@VENUE Venue where the session takes place", "passthrough")


def test_pdf_source_uses_the_injected_converter(tmp_path):
    p = tmp_path / "dd.pdf"
    p.write_bytes(b"%PDF-1.4 stub")
    fake = _FakeConverter("converted markdown text")
    markdown, backend = dd_to_markdown(p, converter=fake)
    assert markdown == "converted markdown text"
    assert backend == "explicit"
    assert fake.calls == [str(p)]
