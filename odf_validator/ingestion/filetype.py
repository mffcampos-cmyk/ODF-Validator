from __future__ import annotations
from pathlib import Path
from lxml import etree

XSD_SUFFIXES = {".xsd"}
EXCEL_SUFFIXES = {".xlsx"}
DD_SUFFIXES = {".pdf", ".docx", ".md", ".markdown"}


def classify_file(path: Path) -> str:
    """Type a dropped-in source file by extension, with light content sniffing
    for .xml (which could be Common Codes or something unrelated).

    .md/.markdown count as a Data Dictionary source too: some DDs arrive
    already converted to Markdown (this repo's docs/source/*.md), and
    dd_to_markdown() (see convert.py) passes those through unchanged instead
    of running them through the PDF/Word converter.
    """
    suffix = path.suffix.lower()
    if suffix in XSD_SUFFIXES:
        return "xsd"
    if suffix in EXCEL_SUFFIXES:
        return "codes"
    if suffix in DD_SUFFIXES:
        return "dd"
    if suffix == ".xml":
        return "codes" if _is_codeset_xml(path) else "unknown"
    return "unknown"


def _is_codeset_xml(path: Path) -> bool:
    try:
        tree = etree.parse(str(path))
    except (etree.XMLSyntaxError, OSError):
        return False
    return tree.find(".//Codeset") is not None
