from __future__ import annotations
import re
from ..model import Finding, Location, Layer, Severity
from .defs_model import RuleDef


def _loc(root, node) -> Location:
    return Location(line=getattr(node, "sourceline", None),
                    path=root.getroottree().getpath(node))


def _finding(rule: RuleDef, root, node, msg: str) -> Finding:
    return Finding(rule.severity, rule.layer, rule.id, msg,
                   _loc(root, node), rule.source_ref)


def value_format(root, rule: RuleDef, registry, ctx) -> list[Finding]:
    regex = rule.params.get("regex")
    forbid = rule.params.get("forbid_substring")
    # Some Extension-style elements document an attribute's format as
    # conditional on a sibling attribute's value (almost always @Code): the
    # same @Pos means "attempt number, 1-3" for one Extension @Code and
    # "not applicable, never sent" for another on the very same tag (ATH DD:
    # Extension@Code=AFTER_ATTEMPT_RANK vs AFTER_ATTEMPT_BEST; GAR DD:
    # ExtendedResult@Code=STAGE vs START_APPARATUS). A plain `target` of
    # `.//*[@Pos]` cannot express that split -- ElementPath has no `or`/
    # `not()` to combine several `[@Code='X']` predicates, and ATH/GAR both
    # reuse the same tag for numeric and non-numeric Codes alike.
    # `context_attr` names the sibling attribute and `context_values` the
    # values for which the format check applies; nodes whose context
    # attribute is absent or not in that set are skipped entirely, same
    # opt-in idiom as code_membership's exclude_tags/column (a rules review,
    # 2026-08-30 -- see ATH_POS_POSINT/GAR_POS_POSINT).
    context_attr = rule.params.get("context_attr")
    context_values = set(rule.params.get("context_values") or [])
    out: list[Finding] = []
    for node in root.findall(rule.target):
        if context_attr and node.get(context_attr) not in context_values:
            continue
        val = node.get(rule.attribute)
        if val is None:
            continue
        if regex is not None and re.fullmatch(regex, val) is None:
            out.append(_finding(rule, root, node,
                                f"@{rule.attribute}='{val}' does not match {regex}."))
        if forbid is not None and forbid in val:
            out.append(_finding(rule, root, node,
                                f"@{rule.attribute}='{val}' must not contain "
                                f"'{forbid}'."))
    return out


def value_domain(root, rule: RuleDef, registry, ctx) -> list[Finding]:
    lo = rule.params.get("min")
    hi = rule.params.get("max")
    integer = rule.params.get("integer", False)
    out: list[Finding] = []
    for node in root.findall(rule.target):
        val = node.get(rule.attribute)
        if val is None:
            continue
        try:
            num = int(val) if integer else float(val)
        except ValueError:
            kind = "an integer" if integer else "a number"
            out.append(_finding(rule, root, node,
                                f"@{rule.attribute}='{val}' must be {kind}."))
            continue
        if lo is not None and num < lo:
            out.append(_finding(rule, root, node,
                                f"@{rule.attribute}={val} is below minimum {lo}."))
        if hi is not None and num > hi:
            out.append(_finding(rule, root, node,
                                f"@{rule.attribute}={val} is above maximum {hi}."))
    return out


def code_membership(root, rule: RuleDef, registry, ctx) -> list[Finding]:
    codeset = rule.params.get("codeset")
    field = rule.params.get("field")
    code_attr = rule.params.get("code_attr")
    # Some Common Codes tables carry two code-shaped columns: the row's own
    # 34-char RSC key, plus a short business code documented as its own column
    # (e.g. PHASE's 'Phase', EVENT_UNIT's 'Eventunit', DISCIPLINE's 'Id'). The
    # DD is explicit about which one an attribute uses via its own
    # 'CC@TABLE Column' notation; `column` mirrors that so a rule can match
    # against the named column's values instead of the table's row key.
    # Case/separator-insensitive (CodeTable.resolve_field) since the DD's
    # spelling and the workbook header don't always agree on case. Applies to
    # both the plain membership check below and the code_attr paired-lookup
    # path (`field` + `code_attr`): the same short code drives both, so a
    # description lookup keyed off the wrong column is exactly as broken as a
    # membership check keyed off it (see GEN_CATEGORYNAME_CODE, which used
    # `code_attr: Category` against a table keyed by RSC and so never matched
    # any row -- a false negative, not merely a false positive).
    column = rule.params.get("column")
    # Documented sentinel values that are legal without appearing in the code
    # table, e.g. 'TBD' for @Venue/@Location on unscheduled units (GEN doc
    # 20548/20551: "Can use TBD if the Venue is not known yet"). Opt-in per rule.
    allow = set(rule.params.get("allow") or [])
    # Element tags to skip even though they match `target`: the same attribute
    # name can be documented as two unrelated things depending on which element
    # carries it. @Unit is an EVENT_UNIT/PHASE RSC on competition elements
    # (Competitor, Config, ...) but is also the measurement-unit attribute on
    # the weather blocks (GEN DD: Weather/Conditions/{Precipitation, Pressure,
    # Temperature, Wind} and Venue/DateTime/Conditions/{same}), documented
    # against SCGEN@PrecipitationUnit/@PressureUnit/@TemperatureUnit/@WindUnit
    # -- none of which are EVENT_UNIT or PHASE codes. A broad target of
    # `.//*[@Unit]` therefore flagged 100% of weather blocks, four attributes
    # at a time, on every discipline that sends DT_WEATHER (audit
    # 2026-08-30/item1). Opt-in per rule via params.exclude_tags, same idiom
    # as sibling_duplicates.
    exclude_tags = set(rule.params.get("exclude_tags") or [])
    table = registry.table(codeset) if registry is not None else None
    if table is None:
        return []
    resolved_column: str | None = None
    if column:
        resolved_column = table.resolve_field(column)
        if resolved_column is None:
            # Unknown column: same class of authoring error as an unknown
            # codeset (builder.py surfaces it as a pack-load error). Skip
            # silently at runtime rather than raise or fall back to RSC
            # matching, which would just reintroduce the false positives this
            # param exists to fix.
            return []
    out: list[Finding] = []
    field_values: set[str] | None = None  # built lazily for field-only checks
    column_index: dict[str, "CodeRow"] | None = None  # built lazily for column+code_attr
    for node in root.findall(rule.target):
        if node.tag in exclude_tags:
            continue
        val = node.get(rule.attribute)
        if val is None:
            continue
        if val in allow:
            continue
        if field:
            # Description attributes (VenueName, EventName, ...): the docs
            # define them as a Common Codes *description*, not the code itself
            # (e.g. GEN "Venue ENG Description (not code) from Common Codes").
            code = node.get(code_attr) if code_attr else None
            if code is not None:
                # The paired code attribute is on the node: require the exact
                # description of that code. If `column` names the column the
                # code actually lives in (e.g. DISCIPLINE's short 'Id'), look
                # the row up by that column's value instead of the table's RSC
                # key, which `code` will never match.
                if resolved_column:
                    if column_index is None:
                        column_index = table.index_by_field(resolved_column)
                    row = column_index.get(code)
                    expected = row.fields.get(field) if row else None
                else:
                    expected = table.get(code, field)
                if expected is not None and val != expected:
                    out.append(_finding(rule, root, node,
                                        f"@{rule.attribute}='{val}' should be the "
                                        f"{field} of {codeset} code '{code}' "
                                        f"('{expected}')."))
            else:
                # No paired code available (e.g. VenueDescription elements):
                # the value must at least be one of the codeset's descriptions.
                if field_values is None:
                    field_values = table.field_values(field)
                if val not in field_values:
                    out.append(_finding(rule, root, node,
                                        f"@{rule.attribute}='{val}' is not a "
                                        f"{field} of any {codeset} code."))
        elif resolved_column:
            if field_values is None:
                field_values = table.field_values(resolved_column)
            if val not in field_values:
                out.append(_finding(rule, root, node,
                                    f"@{rule.attribute}='{val}' is not a valid "
                                    f"{codeset} code (column '{column}')."))
        else:
            if table.lookup(val) is None:
                out.append(_finding(rule, root, node,
                                    f"@{rule.attribute}='{val}' is not a valid "
                                    f"{codeset} code."))
    return out


def conditional_presence(root, rule: RuleDef, registry, ctx) -> list[Finding]:
    when_attr = rule.params.get("when_attr")
    when_equals = rule.params.get("when_equals")
    require = rule.params.get("require")
    forbid = rule.params.get("forbid")
    forbid_child = rule.params.get("forbid_child")
    out: list[Finding] = []
    for node in root.findall(rule.target):
        actual = node.get(when_attr)
        triggered = (actual is not None) if when_equals == "*" else (actual == when_equals)
        if not triggered:
            continue
        cond = (f"@{when_attr}"
                f"{'' if when_equals == '*' else '=' + str(when_equals)}")
        if require and node.get(require) is None:
            out.append(_finding(rule, root, node,
                                f"@{require} is required when {cond}."))
        if forbid and node.get(forbid) is not None:
            out.append(_finding(rule, root, node,
                                f"@{forbid} must not be present when {cond}."))
        if forbid_child and node.find(forbid_child) is not None:
            out.append(_finding(rule, root, node,
                                f"child element '{forbid_child}' must not be "
                                f"sent when {cond}."))
    return out


def set_filter(root, rule: RuleDef, registry, ctx) -> list[Finding]:
    allowed = set(str(a) for a in rule.params.get("allowed", []))
    out: list[Finding] = []
    for node in root.findall(rule.target):
        val = node.get(rule.attribute)
        if val is None:
            continue
        if val not in allowed:
            out.append(_finding(rule, root, node,
                                f"@{rule.attribute}='{val}' is not allowed here "
                                f"(allowed: {sorted(allowed)})."))
    return out


def cross_message(root, rule: RuleDef, registry, ctx) -> list[Finding]:
    if ctx is None:
        # No batch context: cross-message checks only run in batch mode. Skip
        # silently to avoid a per-message info note on every single-file run.
        return []
    key_attr = rule.params.get("key_attr")
    out: list[Finding] = []
    for node in root.findall(rule.target):
        val = node.get(rule.attribute)
        if val is None:
            continue
        key = f"{rule.id}:{node.get(key_attr)}"
        if ctx.has(key):
            prev = ctx.recall(key)
            if prev != val:
                out.append(_finding(rule, root, node,
                                    f"@{rule.attribute}='{val}' for {key_attr}="
                                    f"'{node.get(key_attr)}' is inconsistent with "
                                    f"an earlier message ('{prev}')."))
        else:
            ctx.remember(key, val)
    return out


def no_empty_attributes(root, rule: RuleDef, registry, ctx) -> list[Finding]:
    """Flag any attribute present with an empty (or whitespace-only) value.

    ODF convention: an attribute with no value must be omitted, not sent empty
    (e.g. TeamType="", UnitNum="", Organisation="", IRM=""). `target` defaults to
    the message root plus all descendant elements (self-or-descendant, since
    ElementPath's ".//*" cannot express that and lxml's findall has no
    descendant-or-self axis); `exempt` lists attribute names allowed to be
    empty.
    """
    exempt = set(rule.params.get("exempt", []))
    target = rule.target or ".//*"
    nodes = root.iter("*") if target == ".//*" else root.findall(target)
    out: list[Finding] = []
    for node in nodes:
        for attr, val in node.attrib.items():
            if attr in exempt:
                continue
            if val is not None and str(val).strip() == "":
                out.append(_finding(rule, root, node,
                                    f"@{attr} is sent empty. ODF recommends omitting "
                                    f"empty optional attributes to reduce message "
                                    f"size (Foundation Principles 6.7); mandatory "
                                    f"attributes may legitimately be empty."))
    return out


def forbidden_value(root, rule: RuleDef, registry, ctx) -> list[Finding]:
    """Flag nodes whose attribute holds a denylisted value (e.g. Competitor
    @Code='TBD', which per the GEN doc means the element should not be sent)."""
    forbidden = set(str(v) for v in rule.params.get("values", []))
    reason = rule.params.get("reason", "")
    out: list[Finding] = []
    for node in root.findall(rule.target):
        val = node.get(rule.attribute)
        if val is not None and val in forbidden:
            msg = f"@{rule.attribute}='{val}' is not allowed here."
            if reason:
                msg += " " + reason
            out.append(_finding(rule, root, node, msg))
    return out


def required_attributes(root, rule: RuleDef, registry, ctx) -> list[Finding]:
    """Flag target nodes missing any of params.attrs, or carrying them empty.

    Used by the core envelope rule so required ODF envelope fields are still
    checked when a pack's XSD is inactive (hard-gate mode)."""
    attrs = rule.params.get("attrs", [])
    out: list[Finding] = []
    for node in root.findall(rule.target or "."):
        for a in attrs:
            val = node.get(a)
            if val is None or not val.strip():
                out.append(_finding(rule, root, node,
                                    f"@{a} is required and must be non-empty."))
    return out


def sibling_duplicates(root, rule: RuleDef, registry, ctx) -> list[Finding]:
    """Group target nodes by (parent, tag, attribute value) and act on
    duplicate groups.

    mode="forbid": flag every node in a duplicate group (e.g. two Result
    siblings sharing a SortOrder -- an observed defect class in live feeds).
    mode="require_attr": nodes in a duplicate group must carry
    params.require_attr == params.require_value (e.g. tied Ranks must carry
    RankEqual="Y" -- a defect reported repeatedly across disciplines).

    params.exclude_tags skips element tags for which the sibling axis is the
    wrong comparison. The grouping assumes siblings are distinct competitors
    in one ranked list (Result, Entry, StatsItem). That does not hold for
    <ExtendedResult>, whose siblings are the SAME competitor at successive
    split points (@Pos): SWM DD line 706 defines its @SortOrder per split
    ("Index based on whole list ... sorted by the intermediate passed most
    recently") and its @Rank as the "cumulative rank of the competitor for
    this specific ExtendedResult". Repeats there are documented-valid -- the
    DD's own sample at line 726 carries Rank="1"/SortOrder="1" on both Pos=3
    and Pos=F (19,103 false positives in a single swimming run)."""
    mode = rule.params.get("mode", "forbid")
    req_attr = rule.params.get("require_attr")
    req_val = rule.params.get("require_value")
    exclude_tags = set(rule.params.get("exclude_tags", ()))
    tree = root.getroottree()
    groups: dict[tuple, list] = {}
    for node in root.findall(rule.target):
        val = node.get(rule.attribute)
        if val is None:
            continue
        if node.tag in exclude_tags:
            continue
        parent = node.getparent()
        # lxml proxies are transient: id() is not a stable identity. Use the
        # parent's tree path, which is stable for the lifetime of the parse.
        parent_key = tree.getpath(parent) if parent is not None else ""
        key = (parent_key, node.tag, val)
        groups.setdefault(key, []).append(node)
    out: list[Finding] = []
    for (_, tag, val), nodes in groups.items():
        if len(nodes) < 2:
            continue
        if mode == "forbid":
            for n in nodes:
                out.append(_finding(rule, root, n,
                                    f"@{rule.attribute}='{val}' is duplicated "
                                    f"across {len(nodes)} sibling <{tag}> "
                                    f"elements; it must be unique."))
        elif mode == "require_attr":
            for n in nodes:
                if n.get(req_attr) != req_val:
                    out.append(_finding(rule, root, n,
                                        f"<{tag}> shares @{rule.attribute}="
                                        f"'{val}' with {len(nodes) - 1} sibling(s) "
                                        f"but @{req_attr}='{req_val}' is missing."))
    return out


def no_empty_elements(root, rule: RuleDef, registry, ctx) -> list[Finding]:
    """Flag elements that carry no attributes, no child elements and no text.

    Such elements convey nothing and live feeds have been rejected over
    them (e.g. an empty <ExtendedResults/> node failing the official schema).
    The message root is never flagged; params.exempt lists tag names allowed
    to be empty."""
    exempt = set(rule.params.get("exempt", []))
    target = rule.target or ".//*"
    nodes = root.iter("*") if target == ".//*" else root.findall(target)
    out: list[Finding] = []
    for node in nodes:
        if node is root or node.tag in exempt:
            continue
        has_text = node.text is not None and node.text.strip() != ""
        if not node.attrib and len(node) == 0 and not has_text:
            out.append(_finding(rule, root, node,
                                f"<{node.tag}> is empty (no attributes, children "
                                f"or text); empty elements must be omitted."))
    return out


def allowed_child_tags(root, rule: RuleDef, registry, ctx) -> list[Finding]:
    """Flag any child element of a target node whose tag is not in params.allowed.

    Defense-in-depth against XSD masking: libxml2 validates ordered sequences in
    a single pass, so when a parent element is itself rejected (e.g. an
    out-of-order <ExtendedInfo>) it never descends into that parent's content and
    a misnamed child (e.g. <ExtensionElem> for the documented <Extension>) yields
    no schema error. This rule checks child tags directly, independent of the
    parent's position. `target` selects the parent element(s); params.allowed is
    the whitelist of permitted child tag names; params.ignore lists child tags to
    skip (e.g. comments/PIs are already skipped)."""
    allowed = set(rule.params.get("allowed", []))
    ignore = set(rule.params.get("ignore", []))
    out: list[Finding] = []
    for parent in root.findall(rule.target):
        for child in parent:
            tag = child.tag
            if not isinstance(tag, str):  # comment / processing instruction
                continue
            if tag in ignore or tag in allowed:
                continue
            out.append(_finding(rule, root, child,
                                f"<{tag}> is not a permitted child of "
                                f"<{parent.tag}>; allowed: {sorted(allowed)}."))
    return out


def rsc_components(root, rule: RuleDef, registry, ctx) -> list[Finding]:
    """Check filler integrity within each component of a 34-character RSC.

    FND 10.3 defines the RSC as five components in hierarchical order --
    discipline (3), gender (1), event type (8) + event modifier (10), phase (4)
    and unit (8) -- and states that the dash "is used as a filler, it is used
    when a part of the code is not applicable" with "right padding with the
    filler character in any part of the RSC when the respective code is less
    characters than the maximum length of this part".

    So inside any one component a filler may only ever be followed by more
    filler. `ATHM---100M-----------FNL-0001----` is malformed: the event type
    reads `---100M-`, which left-pads instead of right-pads and would silently
    mis-key any consumer splitting the RSC by offset.

    params.widths is the component layout (default [3, 1, 8, 10, 4, 8]) and
    params.filler the padding character (default "-"). Values whose length does
    not match the layout are skipped: overall shape is CORE_DOCCODE_RSC_FORMAT's
    job and reporting it twice helps nobody."""
    widths = rule.params.get("widths") or [3, 1, 8, 10, 4, 8]
    filler = rule.params.get("filler", "-")
    names = rule.params.get("names") or ["discipline", "gender", "event type",
                                         "event modifier", "phase", "unit"]
    total = sum(widths)
    out: list[Finding] = []
    for node in root.findall(rule.target or "."):
        val = node.get(rule.attribute)
        if val is None or len(val) != total:
            continue
        pos = 0
        for i, width in enumerate(widths):
            part = val[pos:pos + width]
            pos += width
            stripped = part.rstrip(filler)
            if filler not in stripped:
                continue
            name = names[i] if i < len(names) else f"component {i + 1}"
            out.append(_finding(
                rule, root, node,
                f"@{rule.attribute}='{val}': the {name} component "
                f"'{part}' (characters {pos - width + 1}-{pos}) has data after "
                f"a '{filler}' filler. The filler is right padding only "
                f"(Foundation Principles 10.3)."))
    return out


def _sort_key(node, by: list[str], numeric: bool):
    """Key tuple for one sibling, or None if any key attribute is missing or
    (under numeric comparison) not a number -- such siblings are skipped:
    presence and value shape are other rules' jobs."""
    key = []
    for attr in by:
        v = node.get(attr)
        if v is None:
            return None
        if numeric:
            try:
                v = float(v)
            except ValueError:
                return None
        key.append(v)
    return tuple(key)


def sort_order(root, rule: RuleDef, registry, ctx) -> list[Finding]:
    """Report children of each target that are not in the order the DD's
    Message Sort section demands.

    Every SYOG26 discipline DD carries such a section ("The message is sorted
    by Team @Code", GEN 2.1.3.6) and, until this primitive, nothing checked
    it: CORE_SORTORDER_* check @SortOrder's value shape, not the order of
    anything.

    params.child is the sibling tag compared, params.by the key attributes in
    precedence order, params.compare "lexical" (default) or "numeric" --
    lexically 10 sorts before 2, so a rule on @SortOrder must say numeric --
    and params.descending flips the direction. A sibling missing a key, or
    with a non-numeric key under numeric comparison, is skipped. One finding
    per offending sibling, at that sibling.
    """
    child = rule.params.get("child")
    by = list(rule.params.get("by") or ([rule.attribute] if rule.attribute else []))
    if not child or not by:
        return []
    numeric = rule.params.get("compare", "lexical") == "numeric"
    descending = bool(rule.params.get("descending", False))
    out: list[Finding] = []
    for parent in root.findall(rule.target or "."):
        prev_key, prev_node = None, None
        for node in parent:
            if node.tag != child:
                continue
            key = _sort_key(node, by, numeric)
            if key is None:
                continue
            if prev_key is not None and (key > prev_key if descending else key < prev_key):
                keys = ", ".join(f"@{a}={node.get(a)!r}" for a in by)
                prev = ", ".join(f"@{a}={prev_node.get(a)!r}" for a in by)
                out.append(_finding(
                    rule, root, node,
                    f"<{child}> {keys} follows <{child}> {prev}; the message "
                    f"must be sorted by {' then '.join('@' + a for a in by)}"
                    f"{' descending' if descending else ''}"
                    f"{' (numeric)' if numeric else ''}."))
            prev_key, prev_node = key, node
    return out


def _instant(value: str):
    """A comparable datetime for an ODF date or datetime string, or None.

    ODF writes dates as YYYY-MM-DD and datetimes as ISO 8601 with an offset;
    a trailing Z is accepted too. Anything else is not this rule's business.
    """
    from datetime import datetime
    if value is None:
        return None
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        return None


def datetime_order(root, rule: RuleDef, registry, ctx) -> list[Finding]:
    """Report a target whose params.later date/datetime precedes its
    params.earlier one -- a Session with EndDate before StartDate.

    No document states this, so it cannot be drafted from a Data Dictionary;
    it is a hand-written pack rule. params.allow_equal (default true) accepts
    equal instants. A value that does not parse, or a naive datetime paired
    with an aware one (there is no honest way to order those), is skipped:
    format is value_format's job.
    """
    earlier, later = rule.params.get("earlier"), rule.params.get("later")
    if not earlier or not later:
        return []
    allow_equal = bool(rule.params.get("allow_equal", True))
    out: list[Finding] = []
    for node in root.findall(rule.target or "."):
        a, b = _instant(node.get(earlier)), _instant(node.get(later))
        if a is None or b is None or (a.tzinfo is None) != (b.tzinfo is None):
            continue
        if b < a or (not allow_equal and b == a):
            out.append(_finding(
                rule, root, node,
                f"<{node.tag}> @{later}='{node.get(later)}' is "
                f"{'not after' if not allow_equal and b == a else 'before'} "
                f"@{earlier}='{node.get(earlier)}'."))
    return out


PRIMITIVES = {
    "value_format": value_format,
    "rsc_components": rsc_components,
    "value_domain": value_domain,
    "code_membership": code_membership,
    "conditional_presence": conditional_presence,
    "set_filter": set_filter,
    "cross_message": cross_message,
    "no_empty_attributes": no_empty_attributes,
    "forbidden_value": forbidden_value,
    "required_attributes": required_attributes,
    "sibling_duplicates": sibling_duplicates,
    "no_empty_elements": no_empty_elements,
    "allowed_child_tags": allowed_child_tags,
    "sort_order": sort_order,
    "datetime_order": datetime_order,
}
