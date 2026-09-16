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
from .dd_obligations import parse_dd, DDFacts
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


def _drop_unmatched_codesets(drafts: list, registry: CodeRegistry,
                             report: LoadReport) -> list:
    """Refuse to offer a draft whose codeset the workbook cannot provide.

    The load-time drop in load_rule_defs makes such a rule harmless, but it
    treats the symptom once per startup while the cause -- the DD text --
    reopens it on every import: derive, approve, drop, repeat. Refusing here
    ends that loop, and the refusal is recorded so the operator can see what
    the document asked for.

    Only when the pack has tables to judge against, exactly as in
    load_rule_defs: with no workbook loaded, an unknown name says nothing
    about the rule, and hiding the DD's content from the reviewer for that
    reason would be worse than offering it.
    """
    if not registry.names():
        return drafts
    kept = []
    for d in drafts:
        entry = d.to_yaml_dict()
        cs = (entry.get("params") or {}).get("codeset")
        if cs and registry.resolve(cs) is None:
            report.unmatched_codesets.append(
                f"{entry.get('source_ref')}: asks for codeset '{cs}', which "
                f"the Common Codes do not provide under any spelling -- no "
                f"draft rule was offered for @{entry.get('attribute')}.")
            continue
        kept.append(d)
    return kept


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
    if root_name and root_xsd is None and xsd_paths:
        report.schema_unavailable.append(
            f"pack.yaml names root_xsd '{root_name}', which is not one of the "
            f"{len(xsd_paths)} XSD file(s) in this ruleset; falling back to "
            f"the heuristic root.")
    if root_xsd is None:
        root_xsd = next((p for p in xsd_paths if p.name == "odf2.xsd"),
                        xsd_paths[0] if xsd_paths else None)
    if root_xsd is None:
        # Not "falling back to heuristic": there is nothing to fall back to.
        # The heuristic above picks a root from the XSDs present and there
        # are none, so no message may imply a schema is in use.
        report.schema_unavailable.append(
            "This ruleset holds no XSD, so messages are not checked against "
            "the schema at all -- only the rules below run.")
    schema = None
    if root_xsd is not None:
        try:
            schema = compile_schema(root_xsd)
        except Exception as e:
            # Same end state as holding no XSD at all: `schema` stays None
            # and the rules run alone. Same channel, therefore -- and still
            # not a rule that failed to load.
            report.schema_unavailable.append(
                f"The schema did not compile ({root_xsd.name}: {e}), so "
                f"messages are not checked against it -- only the rules "
                f"below run.")

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
    _req_pairs, _decl_pairs, _unamb_pairs, _single_owner = _xsd_attribute_pairs(root_xsd)
    _child_decl, _child_req, _child_single, _unamb_elements = _xsd_child_pairs(root_xsd)
    obligations = ObligationRegistry(xsd_required=_req_pairs,
                                     xsd_declared=_decl_pairs,
                                     xsd_unambiguous=_unamb_pairs,
                                     xsd_single_owner=_single_owner,
                                     xsd_child_declared=_child_decl,
                                     xsd_child_required=_child_req,
                                     xsd_child_single=_child_single,
                                     xsd_unambiguous_elements=_unamb_elements)
    general = DDFacts()
    seen_dds: set[str] = set()
    disciplines: set[str] = set()
    for dd_path, discipline in scan.dd_files:
        if discipline:
            disciplines.add(discipline)
        rel = str(dd_path.relative_to(ruleset_dir))
        seen_dds.add(rel)
        current_hash = hash_file(dd_path)

        cached = ob_store.get_facts(rel, current_hash)
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
            cached = parse_dd(markdown)
            ob_store.put_facts(rel, current_hash, cached)
        if cached and (cached.obligations or cached.widths or cached.cardinalities):
            # A DD with no discipline (the GEN DD, Foundation Principles) is the
            # general authority; a discipline DD binds only its own discipline.
            if discipline:
                obligations.add_discipline(discipline, cached.obligations,
                                           widths=cached.widths,
                                           cardinalities=cached.cardinalities)
            else:
                general.obligations.update(cached.obligations)
                general.widths.update(cached.widths)
                general.cardinalities.update(cached.cardinalities)
                obligations.set_general(general.obligations,
                                        widths=general.widths,
                                        cardinalities=general.cardinalities)

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
            drafts = _drop_unmatched_codesets(drafts, registry, report)
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
     rule_specialised) = load_rule_defs(
        rule_paths, resolve_codeset=registry.resolve,
        # Only when there are tables to judge against: see the notice below.
        drop_unresolvable_codesets=bool(registry.names()))
    report.errors += rule_errors
    report.conflicts += rule_conflicts
    report.deduped += rule_deduped
    report.specialised += rule_specialised

    # Rules whose codeset resolves to nothing were already dropped by
    # load_rule_defs, and reported through rule_errors -- deliberately there
    # rather than here, so a dead rule cannot stand the GEN rule down for its
    # discipline on the way out (see that function's docstring).
    #
    # A pack with no code tables at all is a different case: every codeset
    # name is unknown for a reason that has nothing to do with the rules, so
    # nothing is DROPPED and nothing failed to load. It is the normal state
    # of a fresh clone of the public repository, which ships the authored
    # rules and none of the IOC documents.
    #
    # One note, not one per rule. This used to list every affected rule, on
    # `errors`, on the reasoning that a summary would leave an operator
    # hunting for which rules were involved. On a real first launch that
    # produced 52 lines differing only by rule id, under a banner reading
    # "54 rule(s) failed to load" while 89 rules were active -- and with no
    # tables at all the answer to "which rules" is "every one of them",
    # which the count states outright. `deduped` and `specialised` already
    # report derivable bulk facts this way.
    codeset_rules = [r for r in rules if r.params.get("codeset")]
    if not registry.names() and codeset_rules:
        report.codes_unavailable.append(
            f"No code tables are loaded, so {len(codeset_rules)} "
            f"code_membership rule(s) cannot fire. Import the Common Codes "
            f"workbook from the publication page (Rulesets -> check and "
            f"download updates -> apply), then reload.")
    for r in rules:
        cs = r.params.get("codeset")
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
    # An unknown column leaves the rule in place, unlike an unknown codeset.
    # Deliberate, for now: it is the same silent-pass problem and wants the
    # same treatment, but nothing in this pack is in that state, and a
    # behaviour change nobody asked for does not belong in this fix.

    return RulePack(obligations=obligations, name=name, version=str(manifest.get("version", "") or ""), xsd_paths=xsd_paths, root_xsd=root_xsd,
                     schema=schema, codes=registry, rules=rules,
                     disciplines=sorted(disciplines), report=report,
                     length_exempt=_length_exempt(manifest, report))


def _length_exempt(manifest: dict, report) -> frozenset:
    """pack.yaml `length_exempt: ["ItemName/@Value", ...]` -> {(element, attribute)}.

    A malformed entry is reported and skipped rather than silently widening
    or narrowing what is enforced."""
    out = set()
    for item in manifest.get("length_exempt") or []:
        element, sep, attribute = str(item).partition("/@")
        if not sep or not element.strip() or not attribute.strip():
            report.errors.append(
                f"pack.yaml length_exempt entry {item!r} is not of the form "
                f"Element/@Attribute; ignored.")
            continue
        out.add((element.strip(), attribute.strip()))
    return frozenset(out)


def _xsd_attribute_pairs(root_xsd):
    """(required pairs, declared pairs, unambiguous pairs, single-owner pairs).

    `required` is the last link in the authority chain, consulted only where
    neither the sport DD nor the GEN DD says anything. `declared` is every
    attribute the schema allows on an element, used to discard Data Dictionary
    rows that cannot be right.

    Both are resolved through element NAME because that is what a validation
    finding reports; an element whose complexType is reused under several names
    contributes a pair for each name.
    """
    if root_xsd is None:
        return set(), set(), set(), set()
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
        # Single owner = the attribute is declared under exactly one element
        # name, whatever that name's types. Enough for a check on a value the
        # node actually carries (a width), not for a presence check -- see
        # ObligationRegistry.__init__.
        single_owner = {(name, a) for (name, a) in decl_pairs
                        if len(owners.get(a, ())) == 1}
        return req_pairs, decl_pairs, unambiguous, single_owner
    except Exception:
        return set(), set(), set(), set()


def _xsd_child_pairs(root_xsd):
    """(declared, required, single, unambiguous element names) for
    (parent, child) element pairs.

    `required` means the schema itself demands at least one such child: the
    child has minOccurs >= 1 and NO xs:choice between it and its complexType
    (a choice never requires one particular branch -- the shared
    competitionType puts Result, Entry and Team in one, so an empty
    <Competition/> is schema-valid in every message). `single` means the
    schema caps it at one. Both are used to leave the schema what it already
    reports and enforce only what the Data Dictionary adds.
    """
    if root_xsd is None:
        return set(), set(), set(), set()
    try:
        from lxml import etree
        XS = "{http://www.w3.org/2001/XMLSchema}"
        trees = [etree.parse(str(p)) for p in sorted(root_xsd.parent.glob("*.xsd"))]
        by_type: dict = {}      # complexType -> {child: (required, single)}
        name_types: dict = {}
        for tree in trees:
            for el in tree.iter(XS + "element"):
                name, type_ = el.get("name"), el.get("type")
                if name and type_:
                    name_types.setdefault(name, set()).add(type_)
                if not name:
                    continue
                node, ct, in_choice, repeatable = el.getparent(), None, False, False
                while node is not None:
                    if node.tag == XS + "complexType" and node.get("name"):
                        ct = node.get("name")
                        break
                    if node.tag == XS + "choice":
                        in_choice = True
                    if node.tag in (XS + "choice", XS + "sequence", XS + "all"):
                        if node.get("maxOccurs", "1") != "1":
                            repeatable = True
                        if node.get("minOccurs", "1") == "0":
                            in_choice = True    # an optional group requires nothing
                    node = node.getparent()
                if ct is None:
                    continue
                required = el.get("minOccurs", "1") != "0" and not in_choice
                single = el.get("maxOccurs", "1") == "1" and not repeatable
                by_type.setdefault(ct, {})[name] = (required, single)
        name_types.setdefault("Competition", set()).add("competitionType")
        declared, required, single = set(), set(), set()
        for parent, types in name_types.items():
            for ty in types:
                for child, (req, sgl) in by_type.get(ty, {}).items():
                    declared.add((parent, child))
                    if req:
                        required.add((parent, child))
                    if sgl:
                        single.add((parent, child))
        unambiguous = {n for n, t in name_types.items() if len(t) == 1}
        return declared, required, single, unambiguous
    except Exception:
        return set(), set(), set(), set()
