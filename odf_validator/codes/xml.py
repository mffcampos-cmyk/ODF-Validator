from __future__ import annotations
from pathlib import Path
from lxml import etree
from .tables import CodeRow, CodeTable


def load_xml_codes(path: Path) -> list[CodeTable]:
    tree = etree.parse(str(path))
    tables: list[CodeTable] = []
    for cs in tree.iter("Codeset"):
        name = cs.get("name")
        if not name:
            continue
        table = CodeTable(name)
        for code in cs.iter("Code"):
            cid = code.get("id")
            if not cid:
                continue
            fields = {k: v for k, v in code.attrib.items() if k != "id"}
            table.add_row(CodeRow(id=cid, fields=fields))
        tables.append(table)
    return tables
