from __future__ import annotations
from dataclasses import dataclass, field


def squash_name(s: str) -> str:
    """Lower-case and strip separators, so 'RECORD_TYPE' == 'Recordtype' ==
    'Record Type'. Shared by codes/excel.py (picking a sheet's id column) and
    CodeTable.resolve_field below (matching a rule's `column:` param against
    the actual header key captured from the workbook) -- the Data Dictionary
    and the workbook header don't always agree on case, e.g. DD 'Eventunit'
    vs a header that could read 'EventUnit'."""
    return str(s).lower().replace("_", "").replace(" ", "")


@dataclass
class CodeRow:
    id: str
    fields: dict[str, str] = field(default_factory=dict)


class CodeTable:
    def __init__(self, name: str):
        self.name = name
        self._rows: dict[str, CodeRow] = {}

    def add_row(self, row: CodeRow) -> None:
        self._rows[row.id] = row

    def lookup(self, code: str) -> CodeRow | None:
        return self._rows.get(code)

    def get(self, code: str, field_name: str) -> str | None:
        row = self._rows.get(code)
        return row.fields.get(field_name) if row else None

    def field_values(self, field_name: str) -> set[str]:
        """All distinct non-empty values of one field across the table (e.g.
        every ENG_Description in VENUE)."""
        return {v for row in self._rows.values()
                if (v := row.fields.get(field_name))}

    def resolve_field(self, name: str) -> str | None:
        """Case/separator-insensitive match of `name` against this table's
        field keys, returning the real key (all rows share the same field set,
        captured from the sheet's header row by codes/excel.py). Used for a
        rule's `column:` param, which mirrors the Data Dictionary's own
        'CC@TABLE Column' notation for tables that carry more than one
        code-shaped column (e.g. PHASE's RSC key plus its short 'Phase'
        column). Returns None when no field matches -- an authoring error the
        pack loader reports (see ingestion/builder.py) rather than a silent
        no-op."""
        target = squash_name(name)
        for row in self._rows.values():
            for key in row.fields:
                if squash_name(key) == target:
                    return key
            break  # every row shares the same field set; one is enough
        return None

    def index_by_field(self, field_name: str) -> dict[str, CodeRow]:
        """Reverse index: value of `field_name` -> row (first row wins on a
        duplicate value). Used to resolve a paired code_attr against a named
        column instead of the row's key -- e.g. DISCIPLINE's short 'Id' code
        ('ATH'), while the table itself is keyed by the 34-char RSC."""
        idx: dict[str, CodeRow] = {}
        for row in self._rows.values():
            v = row.fields.get(field_name)
            if v is not None and v not in idx:
                idx[v] = row
        return idx

    def __len__(self) -> int:
        return len(self._rows)


class CodeRegistry:
    def __init__(self):
        self._tables: dict[str, CodeTable] = {}
        self.conflicts: list[str] = []

    def add_table(self, table: CodeTable, source: str) -> list[str]:
        msgs: list[str] = []
        if table.name in self._tables:
            msg = f"Code set '{table.name}' redefined by {source} (last-wins)."
            msgs.append(msg)
            self.conflicts.append(msg)
        self._tables[table.name] = table
        return msgs

    def table(self, name: str) -> CodeTable | None:
        return self._tables.get(name)

    def names(self) -> list[str]:
        return sorted(self._tables)
