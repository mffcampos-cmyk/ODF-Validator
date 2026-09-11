from lxml import etree
from odf_validator import dispatch as dispatch_mod
from odf_validator.dispatch import dispatch

XML = b"""<OdfBody CompetitionCode="SYOG2026" DocumentCode="ARCMTEAM-------"
 DocumentType="DT_RESULT" DocumentSubtype="START_LIST" Version="3"
 Date="2026-01-10" Time="100000000" LogicalDate="2026-01-10"
 FeedFlag="P" Source="ODF">
 <Competition><Discipline Code="ARC"/></Competition></OdfBody>"""


def test_dispatch_reads_attrs():
    info = dispatch(etree.fromstring(XML))
    assert info.doc_type == "DT_RESULT"
    assert info.document_subtype == "START_LIST"
    assert info.version == 3
    assert info.discipline == "ARC"


def test_no_unwired_xsd_selector_is_exposed():
    # `select_xsd(pack, info)` used to live here: it accepted a MessageInfo,
    # ignored it entirely, and returned pack.root_xsd -- and nothing ever
    # called it. The orchestrator compiles and validates against pack.schema
    # directly. An unreachable hook advertises per-message XSD selection that
    # does not exist; if it is ever needed, wire it into the pipeline first.
    assert not hasattr(dispatch_mod, "select_xsd")
