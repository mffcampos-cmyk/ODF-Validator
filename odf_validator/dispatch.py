from __future__ import annotations
from dataclasses import dataclass


@dataclass
class MessageInfo:
    doc_type: str | None
    document_code: str | None
    document_subtype: str | None
    competition_code: str | None
    version: int | None
    discipline: str | None


def dispatch(root) -> MessageInfo:
    g = root.get
    version = g("Version")
    try:
        version = int(version) if version is not None else None
    except (ValueError, TypeError):
        version = None
    discipline = None
    disc_el = root.find("./Competition/Discipline")
    if disc_el is not None:
        discipline = disc_el.get("Code")
    code = g("DocumentCode")
    if not discipline and code:
        discipline = code[:3]
    # ODF spells Competition/Discipline/@Code as a full 34-character RSC
    # ("ARC" followed by 31 dashes). Rule YAML, loader._specialise_by_discipline
    # and the DocumentCode fallback above all use the bare three letters, so
    # every spelling is normalised here -- the one place all consumers share.
    # Reporting the RSC verbatim made rule_applies() skip all 52
    # discipline-scoped rules on conforming messages (a rules review, findings C1/C2).
    # This governs SCOPING only: a message whose @Code is not a full RSC is
    # still invalid input, and the rules that check that read the element.
    if discipline:
        discipline = discipline[:3]
    return MessageInfo(
        doc_type=g("DocumentType"),
        document_code=code,
        document_subtype=g("DocumentSubtype"),
        competition_code=g("CompetitionCode"),
        version=version,
        discipline=discipline,
    )
