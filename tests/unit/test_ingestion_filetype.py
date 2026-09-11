from pathlib import Path
from odf_validator.ingestion.filetype import classify_file


def test_xsd_by_extension(tmp_path):
    p = tmp_path / "odf2.xsd"
    p.write_text("<xsd/>")
    assert classify_file(p) == "xsd"


def test_excel_codes_by_extension(tmp_path):
    p = tmp_path / "codes.xlsx"
    p.write_bytes(b"not a real workbook, extension is enough to type it")
    assert classify_file(p) == "codes"


def test_pdf_data_dictionary_by_extension(tmp_path):
    p = tmp_path / "dd.pdf"
    p.write_bytes(b"%PDF-1.4 stub")
    assert classify_file(p) == "dd"


def test_docx_data_dictionary_by_extension(tmp_path):
    p = tmp_path / "dd.docx"
    p.write_bytes(b"PK stub")
    assert classify_file(p) == "dd"


def test_markdown_data_dictionary_by_extension(tmp_path):
    p = tmp_path / "dd.md"
    p.write_text("# already converted")
    assert classify_file(p) == "dd"


def test_xml_codeset_sniffed_as_codes(tmp_path):
    p = tmp_path / "codes.xml"
    p.write_text('<Codesets><Codeset name="VENUE"><Code id="AAW"/></Codeset></Codesets>')
    assert classify_file(p) == "codes"


def test_xml_non_codeset_is_unknown(tmp_path):
    p = tmp_path / "notes.xml"
    p.write_text("<Notes><Item/></Notes>")
    assert classify_file(p) == "unknown"


def test_unrecognized_extension(tmp_path):
    p = tmp_path / "readme.txt"
    p.write_text("hello")
    assert classify_file(p) == "unknown"


def test_xml_truncated_codeset_is_unknown(tmp_path):
    p = tmp_path / "truncated.xml"
    p.write_text("<Codesets><Codeset name='X'>")
    assert classify_file(p) == "unknown"
