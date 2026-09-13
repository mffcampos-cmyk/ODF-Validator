"""A ruleset with no usable XSD is not a ruleset whose rules failed to load.

The banner a fresh clone of the public repository greeted its operator with:

    1 rule(s) failed to load - first: pack.yaml root_xsd 'odf2.xsd' not
    found; falling back to heuristic.

Two untruths in one line. No rule failed to load -- the pack had not reached
its rule files when this was appended. And there was no fallback: the
heuristic picks a root from the XSDs present, and a public clone has none
(the tree ships the authored rules but not the IOC documents), so `schema`
stays None and the rules run alone.

This is the fourth time the same mislabelling has had to be undone --
dd_unconvertible, cache_warnings and unmatched_codesets were each pulled off
`report.errors` for exactly this reason -- so these tests pin the channel,
not the prose.

Deliberately its own module rather than an addition to
test_ingestion_builder.py: that one is marked `needs_populated_ruleset` as a
whole, and every pack built here is built from scratch in tmp_path, so
gating them on an import that has not happened would leave them unrun in the
one environment where a fresh clone's behaviour actually matters.
"""
from __future__ import annotations
from pathlib import Path

from odf_validator.ingestion.builder import build_ruleset_pack

MINIMAL_XSD = ('<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
               '<xs:element name="A"/></xs:schema>')


def _pack(tmp_path: Path, name: str, manifest: str) -> Path:
    d = tmp_path / name
    d.mkdir()
    (d / "pack.yaml").write_text(manifest, encoding="utf-8")
    return d


def test_a_ruleset_with_no_xsd_at_all_is_not_a_rule_load_failure(tmp_path):
    d = _pack(tmp_path, "FRESHCLONE", "version: '2026.09'\nroot_xsd: odf2.xsd\n")
    pack = build_ruleset_pack(d)

    assert pack.schema is None
    assert pack.root_xsd is None
    assert pack.report.errors == [], pack.report.errors
    assert pack.report.schema_unavailable, (
        "silence is the other failure mode: an operator whose messages are "
        "not being schema-validated has to be told so somewhere")


def test_the_no_xsd_note_does_not_claim_a_fallback_that_did_not_happen(tmp_path):
    """The old wording said 'falling back to heuristic' whether or not there
    was anything to fall back to. With no XSD in the ruleset there is not."""
    d = _pack(tmp_path, "FRESHCLONE2", "root_xsd: odf2.xsd\n")
    note = " ".join(build_ruleset_pack(d).report.schema_unavailable).lower()

    assert "heuristic" not in note, note


def test_a_named_root_xsd_that_is_missing_falls_back_and_says_so(tmp_path):
    """The other half of the branch: the named root is absent but other XSDs
    are present, so the heuristic really does pick one. Worth reporting --
    pack.yaml describes a file that is not there -- and still not a
    rule-load failure."""
    d = _pack(tmp_path, "NAMEDROOTGONE", "root_xsd: nosuch.xsd\n")
    (d / "odf2.xsd").write_text(MINIMAL_XSD, encoding="utf-8")
    pack = build_ruleset_pack(d)

    assert pack.root_xsd is not None and pack.root_xsd.name == "odf2.xsd"
    assert pack.report.errors == [], pack.report.errors
    assert any("nosuch.xsd" in n for n in pack.report.schema_unavailable)


def test_an_xsd_that_does_not_compile_is_reported_off_the_failed_load_line(tmp_path):
    """A schema that will not compile leaves the pack exactly where no
    schema at all leaves it -- `schema` is None and the rules run alone --
    so it belongs on the same channel and is not a rule that failed to load
    either.

    Not hypothetical: the IOC's own published odf2-structure.xsd references
    RecordBrokenType and never defines it, so this is the state a public
    clone reaches the moment the schema fetch starts working.
    """
    d = _pack(tmp_path, "BADXSD", "")
    (d / "odf2.xsd").write_text(
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
        '<xs:element name="A" type="xs:NoSuchType"/></xs:schema>',
        encoding="utf-8")
    pack = build_ruleset_pack(d)

    assert pack.schema is None
    assert pack.report.errors == [], pack.report.errors
    assert any("odf2.xsd" in n for n in pack.report.schema_unavailable)


def test_a_pack_with_no_root_xsd_line_still_says_it_validates_nothing(tmp_path):
    """SOLG28 ships with its root_xsd line commented out, so the missing
    schema produced no message at all -- quiet by accident of the manifest,
    not by design. A pack with no schema is in the same state whether or not
    pack.yaml happens to name a root. Silence here is the shape of how
    '@Class is validated by nothing' survived unnoticed for months."""
    d = _pack(tmp_path, "SCAFFOLD", "version: ''\n")
    pack = build_ruleset_pack(d)

    assert pack.report.errors == []
    assert pack.report.schema_unavailable


def test_a_healthy_pack_says_nothing_about_its_schema(tmp_path):
    """The channel must stay empty when there is nothing wrong, or it
    becomes another permanent banner nobody reads."""
    d = _pack(tmp_path, "HEALTHY", "root_xsd: odf2.xsd\n")
    (d / "odf2.xsd").write_text(MINIMAL_XSD, encoding="utf-8")
    pack = build_ruleset_pack(d)

    assert pack.schema is not None
    assert pack.report.schema_unavailable == []
    assert pack.report.errors == []
