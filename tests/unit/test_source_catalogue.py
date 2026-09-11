from __future__ import annotations
from datetime import date
from pathlib import Path

import pytest

from odf_validator.sources.catalogue import parse_catalogue

BASE = "https://odf.olympictech.org/2026-Dakar/dakar_2026_YOG.html"
FIXTURE = Path(__file__).resolve().parents[1] / "corpus" / "dakar_2026_YOG.html"


@pytest.fixture(scope="module")
def entries():
    return parse_catalogue(FIXTURE.read_text(encoding="utf-8"), BASE)


def test_every_card_is_parsed(entries):
    assert len(entries) == 32


def test_all_twenty_five_data_dictionaries_are_found(entries):
    dds = [e for e in entries if e.kind == "dd"]
    assert len(dds) == 25
    assert {e.discipline for e in dds} == {
        "ARC", "ATH", "BDM", "BK3", "BKG", "BOX", "BS5", "CRD", "EQU", "FBS",
        "FEN", "GAR", "HBB", "JUD", "RCB", "RU7", "SAL", "SKB", "SWM", "TKW",
        "TRI", "TTE", "VBV", "WRB", "WST"}


def test_data_dictionary_entry_fields(entries):
    swm = next(e for e in entries if e.discipline == "SWM")
    assert swm.reference == "YOG-2026-SWM"
    assert swm.published == date(2026, 5, 19)
    assert swm.url == ("https://odf.olympictech.org/2026-Dakar/YOG/"
                       "ODF_SWM_Data_Dictionary.pdf")
    assert swm.target == "Disciplines/SWM/ODF_SWM_Data_Dictionary.pdf"


def test_numeric_discipline_code_is_not_mangled(entries):
    # BK3 and RU7 carry digits; a [A-Z]{3} pattern would drop them.
    assert {"BK3", "RU7"} <= {e.discipline for e in entries if e.kind == "dd"}


def test_common_codes_entry(entries):
    codes = next(e for e in entries if e.kind == "codes")
    assert codes.reference == "YOG-2026-2.2"
    assert codes.published == date(2026, 9, 2)
    assert codes.url.endswith("/2026-Dakar/codes/ZIP/YOG2026_XLS_Codes.zip")
    assert codes.target == "codes/"


def test_schema_entry_resolves_cross_games_relative_href(entries):
    schema = next(e for e in entries if e.kind == "schema")
    assert schema.url == ("https://odf.olympictech.org/2026-MiCo/schema/"
                          "odf-schema.zip")
    assert schema.published is None      # the card says "see Olympic"
    assert schema.target == "xsd/"


def test_general_documents(entries):
    general = {e.reference: e for e in entries if e.kind == "general"}
    assert set(general) == {"SOG-2024-FND", "OWG-2026-GEN",
                            "OWG-2026_CCDEFN", "OWG-2026-NAMES"}
    fnd = general["SOG-2024-FND"]
    # The card offers both PDF and HTML; the PDF is the artifact we want.
    assert fnd.url.endswith(".pdf")
    assert fnd.target == "ODF_Foundation_Principles_R-SOG-2024-FND.pdf"


def test_card_with_no_links_is_unknown_not_dropped(entries):
    hv = next(e for e in entries if e.reference == "YOG-2026-HV")
    assert hv.kind == "unknown"
    assert hv.url == ""
    assert hv.target == ""


def test_missing_date_element_is_none():
    html = """<div class="doc-grid"><div class="doc-card">
      <div class="row1"><div class="title">ODF Judo Data Dictionary</div></div>
      <div class="row2"><div class="ref">Reference: YOG-2026-JUD</div>
      <div class="links"><a class="pdf" href="YOG/ODF_JUD_Data_Dictionary.pdf">PDF</a></div>
      </div></div></div>"""
    entry = parse_catalogue(html, BASE)[0]
    assert entry.published is None
    assert entry.kind == "dd"


def test_a_backslash_in_the_hrefs_last_segment_is_refused_not_classified_general():
    r"""CRITICAL 2 (final whole-branch review): an href whose last path
    segment is '..\..\..\..\Startup\evil.pdf' survives urljoin() and
    PurePosixPath(...).name untouched -- neither treats a backslash as a
    separator, so `name` comes out exactly as written. On POSIX (this
    test's own platform) that is a harmless, oddly-named single file; on
    the Windows host this app actually runs in production, the very same
    string is a real directory traversal once it becomes entry.target. It
    must be refused at classification -- reported as 'unknown', the same as
    a card with no downloadable link at all -- never handed back as a
    'general' entry with a target nothing downstream can safely join. The
    assertion is behavioural (kind/target), not host-path-specific, so it
    holds identically on Linux and Windows.
    """
    href = "general/..\\..\\..\\..\\Startup\\evil.pdf"
    html = (
        '<div class="doc-grid"><div class="doc-card">'
        '<div class="row1"><div class="title">Evil</div></div>'
        '<div class="row2"><div class="ref">Reference: EVIL-1</div>'
        f'<div class="links"><a class="pdf" href="{href}">PDF</a></div>'
        '</div></div></div>'
    )
    entry = parse_catalogue(html, BASE)[0]
    assert entry.kind == "unknown", (
        "a backslash-laden href segment must never classify as 'general'")
    assert entry.target == "", (
        "an 'unknown' entry always carries an empty target, the same as a "
        "card with no downloadable link -- fetch_targets skips every "
        "'unknown'-kind entry regardless of its url, so this alone is "
        "enough to keep the hostile target out of reach")


def test_legitimate_general_and_dd_targets_are_unaffected(entries):
    """The refusal above must not over-refuse anything real: bare filenames,
    the Disciplines/<code>/name.pdf form, and the archive directory markers
    all still classify normally against the real fixture page."""
    gen = next(e for e in entries if e.reference == "OWG-2026-GEN")
    assert gen.kind == "general"
    assert gen.target == "ODF_GEN_R-OWG2026-GEN.pdf"

    swm = next(e for e in entries if e.discipline == "SWM")
    assert swm.target == "Disciplines/SWM/ODF_SWM_Data_Dictionary.pdf"

    codes = next(e for e in entries if e.kind == "codes")
    assert codes.target == "codes/"
    schema = next(e for e in entries if e.kind == "schema")
    assert schema.target == "xsd/"
