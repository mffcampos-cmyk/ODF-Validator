from __future__ import annotations
from pathlib import Path
import yaml

from ..loader.pack import RulePack, LoadReport
from ..codes.tables import CodeRegistry
from ..codes.excel import load_excel_codes
from ..codes.xml import load_xml_codes
from ..pipeline.structural import compile_schema
from ..rules.loader import load_rule_defs
from .scanner import scan_ruleset
from .state import IngestionState, hash_file
from .convert import dd_to_markdown
from .dd_parser import extract_draft_rules
from .draft_store import write_drafts
from .dd_obligations import parse_obligations
from .obligation_store import ObligationStore, STORE_FILE_NAME
from ..rules.obligations import ObligationRegistry


def _note_fallback(report: LoadReport, dd_path: Path, backend: str) -> None:
    """Record that a PDF Data Dictionary was converted by the fallback backend.

    Only PDFs: .docx has no primary backend to fall back FROM (pdf-inspector
    is PDF-only), so markitdown there is the intended route, not a
    degradation. Appended at most once per DD -- a DD can be converted twice
    in one load (once for obligations, once for draft suggestions) and the
    operator needs the fact, not the count.
    """
    if backend != "markitdown" or dd_path.suffix.lower() != ".pdf":
        return
    note = (f"{dd_path.name}: converted by markitdown because pdf-inspector "
            f"failed; obligations parsed from it may be less reliable")
    if note not in report.converted_by_fallback:
        report.converted_by_fallback.append(note)


def build_ruleset_pack(ruleset_dir: Path, converter=None) -> RulePack:
    """Assemble a RulePack from a Rules\\<ruleset>\\ folder: ingest XSD/Common
    Codes directly (deterministic, machine-readable), heuristically draft
    candidate rules from new/changed Data Dictionaries (never active until a
    human approves them -- see draft_store.py), and load every already-approved
    rule file (rules/*.yaml, anywhere under the ruleset tree) as active."""
    name = ruleset_dir.name
    report = LoadReport()
    registry = CodeRegistry()
    scan = scan_ruleset(ruleset_dir)

    manifest: dict = {}
    mf = ruleset_dir / "pack.yaml"
    if mf.exists():
        try:
            loaded = yaml.safe_load(mf.read_text(encoding="utf-8"))
            manifest = loaded if isinstance(loaded, dict) else {}
        except Exception as e:
            report.errors.append(f"pack.yaml unreadable, using defaults: {e}")

    xsd_paths = sorted(scan.xsd_files)
    root_name = manifest.get("root_xsd")
    root_xsd = (next((p for p in xsd_paths if p.name == root_name), None)
                if root_name else None)
    if root_name and root_xsd is None:
        report.errors.append(f"pack.yaml root_xsd '{root_name}' not found; "
                             f"falling back to heuristic.")
    if root_xsd is None:
        root_xsd = next((p for p in xsd_paths if p.name == "odf2.xsd"),
                        xsd_paths[0] if xsd_paths else None)
    schema = None
    if root_xsd is not None:
        try:
            schema = compile_schema(root_xsd)
        except Exception as e:
            report.errors.append(f"XSD did not compile ({root_xsd.name}): {e}")

    for p in scan.code_files:
        try:
            tables = (load_excel_codes(p) if p.suffix.lower() == ".xlsx"
                      else load_xml_codes(p))
            for t in tables:
                report.conflicts += registry.add_table(t, p.name)
            report.loaded_files.append(p.name)
        except Exception as e:
            report.errors.append(f"Failed to load codes {p.name}: {e}")

    for p in scan.unknown_files:
        report.errors.append(f"Unrecognized file, skipped: {p.relative_to(ruleset_dir)}")

    state = IngestionState.load(ruleset_dir / ".ingestion_state.json")
    # Obligations are cached separately from `state`, and unlike the draft
    # suggestions below they are collected for EVERY DD on every load -- an
    # unchanged DD still governs which attributes are mandatory.
    ob_store = ObligationStore.load(ruleset_dir / STORE_FILE_NAME)
    _req_pairs, _decl_pairs, _unamb_pairs = _xsd_attribute_pairs(root_xsd)
    obligations = ObligationRegistry(xsd_required=_req_pairs,
                                     xsd_declared=_decl_pairs,
                                     xsd_unambiguous=_unamb_pairs)
    seen_dds: set[str] = set()
    disciplines: set[str] = set()
    for dd_path, discipline in scan.dd_files:
        if discipline:
            disciplines.add(discipline)
        rel = str(dd_path.relative_to(ruleset_dir))
        seen_dds.add(rel)
        current_hash = hash_file(dd_path)

        cached = ob_store.get(rel, current_hash)
        drafts_needed = state.is_changed(rel, current_hash)
        markdown = None
        if cached is None or drafts_needed:
            try:
                markdown, backend = dd_to_markdown(dd_path, converter=converter)
                _note_fallback(report, dd_path, backend)
            except Exception as e:
                report.dd_unconvertible.append(
                    f"{dd_path.name} could not be converted ({e}); its "
                    f"obligations and draft suggestions are unavailable.")
        if cached is None and markdown is not None:
            cached = parse_obligations(markdown)
            ob_store.put(rel, current_hash, cached)
        if cached:
            # A DD with no discipline (the GEN DD, Foundation Principles) is the
            # general authority; a discipline DD binds only its own discipline.
            if discipline:
                obligations.add_discipline(discipline, cached)
            else:
                merged = dict(getattr(obligations, "_general", {}))
                merged.update(cached)
                obligations.set_general(merged)

        if not drafts_needed:
            continue
        if markdown is None:
            # Reaching here means drafts_needed is True, so the `cached is None
            # or drafts_needed` test above was True and the conversion at the
            # top of this loop already ran. markdown is None therefore means
            # that conversion RAISED -- and it was already recorded in
            # dd_unconvertible. Retrying it would convert the same document a
            # second time (for a PDF: pdf-inspector and markitdown, twice),
            # fail identically, and land the same failure in report.errors as
            # well -- which app.js renders as "N rule(s) failed to load", the
            # exact mislabelling dd_unconvertible was introduced to stop. On a
            # fresh clone drafts_needed is True for every DD, so that is
            # precisely when it would misfire.
            continue
        try:
            drafts = extract_draft_rules(markdown, discipline, dd_path.name)
            if drafts:
                write_drafts(dd_path, [d.to_yaml_dict() for d in drafts])
                report.loaded_files.append(f"{dd_path.name} -> {len(drafts)} draft rule(s)")
            else:
                report.loaded_files.append(f"{dd_path.name} -> 0 draft rules")
        except Exception as e:
            report.errors.append(f"Failed to ingest Data Dictionary {dd_path.name}: {e}")
        else:
            state.update(rel, current_hash)   # only mark processed on success
    state.save()
    # The cache is committed derived data (see obligation_store's docstring),
    # so a scan that cannot account for an entry is a signal, not routine
    # housekeeping: losing a discipline's obligations silently re-enables the
    # XSD false positives the DD authority exists to suppress.
    unaccounted = ob_store.would_shrink(seen_dds)
    dropped = ob_store.prune(seen_dds)
    if unaccounted and not dropped:
        report.cache_warnings.append(
            f"Obligation cache: this scan did not see {unaccounted} cached "
            f"Data Dictionary/ies, so the cache was left intact rather than "
            f"pruned. DD-over-XSD authority may be running on stale data -- "
            f"delete Rules/{name}/{STORE_FILE_NAME} and rebuild with the PDF "
            f"converter installed.")
    ob_store.save()

    rule_paths = sorted(ruleset_dir.rglob("rules/*.yaml"))
    (rules, rule_errors, rule_conflicts, rule_deduped,
     rule_specialised) = load_rule_defs(rule_paths)
    report.errors += rule_errors
    report.conflicts += rule_conflicts
    report.deduped += rule_deduped
    report.specialised += rule_specialised

    # A rule pointing at a codeset the pack doesn't provide can never fire:
    # code_membership skips silently when the table is missing. That masked 24
    # dead rules (documentation typos, e.g. SHEDULESTATUS for SCHEDULESTATUS).
    # Surface it as a pack-load error so misspellings are caught immediately.
    known_codesets = set(registry.names())
    for r in rules:
        cs = r.params.get("codeset")
        if cs and cs not in known_codesets:
            report.errors.append(
                f"Rule {r.id}: codeset '{cs}' is not provided by this pack's "
                f"code tables; the rule will never fire.")
            continue
        # Same failure mode, one level down: `column` names which of a
        # table's code-shaped columns to match (see rules/primitives.py
        # code_membership), mirroring the Data Dictionary's own
        # 'CC@TABLE Column' notation. A column that does not exist on the
        # table is exactly as fatal to the rule as an unknown codeset --
        # code_membership skips silently rather than raise -- so it must be
        # surfaced here too, not left to look like a passing check.
        col = r.params.get("column")
        if cs and col:
            table = registry.table(cs)
            if table is not None and table.resolve_field(col) is None:
                report.errors.append(
                    f"Rule {r.id}: column '{col}' is not a field of codeset "
                    f"'{cs}'; the rule will never fire.")

    return RulePack(obligations=obligations, name=name, version=str(manifest.get("version", "") or ""), xsd_paths=xsd_paths, root_xsd=root_xsd,
                     schema=schema, codes=registry, rules=rules,
                     disciplines=sorted(disciplines), report=report)


def _xsd_attribute_pairs(root_xsd):
    """(required pairs, declared pairs, unambiguous pairs).

    `required` is the last link in the authority chain, consulted only where
    neither the sport DD nor the GEN DD says anything. `declared` is every
    attribute the schema allows on an element, used to discard Data Dictionary
    rows that cannot be right.

    Both are resolved through element NAME because that is what a validation
    finding reports; an element whose complexType is reused under several names
    contributes a pair for each name.
    """
    if root_xsd is None:
        return set(), set(), set()
    try:
        from lxml import etree
        XS = "{http://www.w3.org/2001/XMLSchema}"
        req, decl = {}, {}
        trees = [etree.parse(str(p)) for p in sorted(root_xsd.parent.glob("*.xsd"))]
        for tree in trees:
            for attr in tree.iter(XS + "attribute"):
                if not attr.get("name"):
                    continue
                node = attr.getparent()
                while node is not None and not (
                        node.tag == XS + "complexType" and node.get("name")):
                    node = node.getparent()
                if node is None:
                    continue
                ct = node.get("name")
                decl.setdefault(ct, set()).add(attr.get("name"))
                if attr.get("use") == "required":
                    req.setdefault(ct, set()).add(attr.get("name"))
        # Two passes over elements: a complexType may be defined in a different
        # file from the element that uses it.
        req_pairs, decl_pairs = set(), set()
        name_types: dict = {}
        for tree in trees:
            for el in tree.iter(XS + "element"):
                name, type_ = el.get("name"), el.get("type")
                if not (name and type_):
                    continue
                name_types.setdefault(name, set()).add(type_)
                req_pairs |= {(name, a) for a in req.get(type_, ())}
                decl_pairs |= {(name, a) for a in decl.get(type_, ())}
        name_types.setdefault("Competition", set()).add("competitionType")
        # Competition is the document root's child, declared inline.
        req_pairs |= {("Competition", a) for a in req.get("competitionType", ())}
        decl_pairs |= {("Competition", a) for a in decl.get("competitionType", ())}
        # Unambiguous = safe to enforce a "must be present" check on:
        #   * the element NAME resolves to exactly one complexType, so an
        #     obligation cannot leak between same-named elements of different
        #     types (<Description> is 13 types; a team-only @TeamName would
        #     otherwise be demanded of every athlete and official);
        #   * the attribute is declared on exactly one element in the whole
        #     schema, so a Data Dictionary parse that attributes it to the
        #     wrong element lands somewhere it is not declared and is caught.
        owners: dict = {}
        for name, types in name_types.items():
            for ty in types:
                for a in decl.get(ty, ()):
                    owners.setdefault(a, set()).add(name)
        unambiguous = {
            (name, a)
            for name, types in name_types.items() if len(types) == 1
            for a in decl.get(next(iter(types)), ())
            if len(owners.get(a, ())) == 1
        }
        return req_pairs, decl_pairs, unambiguous
    except Exception:
        return set(), set(), set()
