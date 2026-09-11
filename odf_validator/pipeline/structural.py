from __future__ import annotations
from pathlib import Path
from lxml import etree
from ..model import Finding, Location, Layer, Severity


def compile_schema(xsd_path: Path) -> etree.XMLSchema:
    """Compile an XSD file into an XMLSchema.

    Raises lxml.etree.XMLSchemaParseError on a malformed/incomplete schema;
    the caller (build_ruleset_pack) records that as a pack load error so the
    rest of the pipeline can still run.
    """
    return etree.XMLSchema(etree.parse(str(xsd_path)))


def validate_structural(xml, schema):
    """Validate one message structurally.

    Returns (root_or_None, findings):
      - Malformed XML            -> (None, [ERROR])  caller short-circuits.
      - schema is None           -> (root, [ERROR])  hard-gated: CORE_XSD_INACTIVE.
      - schema present, invalid  -> (root, [ERROR...]).
      - schema present, valid    -> (root, []).
    """
    if isinstance(xml, str):
        xml = xml.encode("utf-8")
    try:
        root = etree.fromstring(xml)
    except (etree.XMLSyntaxError, ValueError) as e:
        line = getattr(e, "lineno", None)
        msg = getattr(e, "msg", None) or str(e)
        return None, [Finding(Severity.ERROR, Layer.STRUCTURAL, "XML_PARSE",
                              f"Malformed XML: {msg}", Location(line=line),
                              "XML well-formedness")]
    if schema is None:
        return root, [Finding(Severity.ERROR, Layer.STRUCTURAL, "CORE_XSD_INACTIVE",
                              "Structural validation is INACTIVE: this pack has no "
                              "compiling XSD. Findings below cannot be considered a "
                              "clean pass. Fix the pack schema (see pack load report).",
                              Location(), "ODF XSD schema (core requirement)")]
    if schema.validate(root):
        return root, []
    findings = []
    for err in schema.error_log:
        findings.append(Finding(Severity.ERROR, Layer.STRUCTURAL, "XSD_INVALID",
                                err.message, Location(line=err.line, path=err.path),
                                "ODF XSD schema"))
    return root, findings
