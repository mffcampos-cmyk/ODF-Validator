from odf_validator.rules.loader import load_rule_defs


def test_loads_valid_rule(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text(
        "- id: T1\n  applies_to: {disciplines: [ARC]}\n  primitive: set_filter\n"
        "  target: './/Unit'\n  attribute: PhaseType\n  params: {allowed: ['0']}\n"
        "  severity: error\n  scope: message\n  source_ref: src\n", encoding="utf-8")
    rules, errors, conflicts, deduped, _spec = load_rule_defs([p])
    assert errors == [] and conflicts == [] and len(rules) == 1
    assert rules[0].id == "T1" and rules[0].applies_to.disciplines == ["ARC"]


def test_bad_rule_becomes_error(tmp_path):
    p = tmp_path / "r.yaml"
    # missing required 'primitive'/'target' keys
    p.write_text("- id: BAD\n", encoding="utf-8")
    rules, errors, conflicts, deduped, _spec = load_rule_defs([p])
    assert rules == [] and len(errors) == 1 and conflicts == []


def test_duplicate_id_across_files_keeps_first_and_reports_conflict(tmp_path):
    p1 = tmp_path / "a.yaml"
    p1.write_text(
        "- id: DUP\n  primitive: set_filter\n  target: './/Unit'\n"
        "  attribute: PhaseType\n  params: {allowed: ['0']}\n"
        "  severity: error\n  scope: message\n  source_ref: from-a\n", encoding="utf-8")
    p2 = tmp_path / "b.yaml"
    p2.write_text(
        "- id: DUP\n  primitive: set_filter\n  target: './/Unit'\n"
        "  attribute: PhaseType\n  params: {allowed: ['1']}\n"
        "  severity: error\n  scope: message\n  source_ref: from-b\n", encoding="utf-8")

    rules, errors, conflicts, deduped, _spec = load_rule_defs([p1, p2])

    assert len(rules) == 1
    assert rules[0].source_ref == "from-a"  # first occurrence wins, deterministically
    assert len(conflicts) == 1
    assert "DUP" in conflicts[0] and "a.yaml" in conflicts[0] and "b.yaml" in conflicts[0]


def test_duplicate_id_within_the_same_file_also_reports_conflict(tmp_path):
    p = tmp_path / "a.yaml"
    p.write_text(
        "- id: DUP\n  primitive: set_filter\n  target: './/Unit'\n"
        "  attribute: PhaseType\n  params: {allowed: ['0']}\n"
        "  severity: error\n  scope: message\n  source_ref: first\n"
        "- id: DUP\n  primitive: set_filter\n  target: './/Unit'\n"
        "  attribute: PhaseType\n  params: {allowed: ['1']}\n"
        "  severity: error\n  scope: message\n  source_ref: second\n", encoding="utf-8")

    rules, errors, conflicts, deduped, _spec = load_rule_defs([p])

    assert len(rules) == 1
    assert rules[0].source_ref == "first"
    assert len(conflicts) == 1


def _rule_yaml(id_, applies_to, source):
    return (
        f"- id: {id_}\n  applies_to: {applies_to}\n  primitive: code_membership\n"
        f"  target: './/*[@RecordType]'\n  attribute: RecordType\n"
        f"  params: {{codeset: RECORD_TYPE}}\n  severity: warning\n  scope: message\n"
        f"  source_ref: {source}\n"
    )


def test_discipline_rule_duplicating_a_global_rule_is_dropped(tmp_path):
    # A global rule (applies_to {}) and a discipline-scoped rule with identical
    # semantics both validate @RecordType. The global rule already covers that
    # discipline, so the discipline copy is redundant and would double-fire.
    # It must be dropped; the broad rule is kept.
    disc = tmp_path / "swm.yaml"
    disc.write_text(_rule_yaml("SWM_RECORDTYPE_CODE", "{disciplines: [SWM]}", "swm"),
                    encoding="utf-8")
    gen = tmp_path / "gen.yaml"
    gen.write_text(_rule_yaml("GEN_RECORDTYPE_CODE", "{}", "gen"), encoding="utf-8")

    # discipline files sort before GEN in real loading -> pass in that order
    rules, errors, conflicts, deduped, _spec = load_rule_defs([disc, gen])

    assert [r.id for r in rules] == ["GEN_RECORDTYPE_CODE"]
    assert errors == []
    # a redundant-copy drop is bookkeeping, not a conflict a human must fix
    assert conflicts == []
    assert any("SWM_RECORDTYPE_CODE" in d and "GEN_RECORDTYPE_CODE" in d
               for d in deduped)


def test_same_check_scoped_to_two_disciplines_keeps_both(tmp_path):
    # Identical semantics but disjoint discipline scope never double-fires on a
    # single message, so both rules must survive.
    a = tmp_path / "a.yaml"
    a.write_text(_rule_yaml("ATH_RECORDTYPE_CODE", "{disciplines: [ATH]}", "a"),
                 encoding="utf-8")
    b = tmp_path / "b.yaml"
    b.write_text(_rule_yaml("BOX_RECORDTYPE_CODE", "{disciplines: [BOX]}", "b"),
                 encoding="utf-8")

    rules, errors, conflicts, deduped, _spec = load_rule_defs([a, b])

    assert {r.id for r in rules} == {"ATH_RECORDTYPE_CODE", "BOX_RECORDTYPE_CODE"}
    assert conflicts == []


def test_rules_with_different_field_are_not_semantic_duplicates(tmp_path):
    # Same attribute but different target field (ENG_Description vs
    # ENG_shortDescription) produce different findings -> not duplicates.
    gen = tmp_path / "gen.yaml"
    gen.write_text(
        "- id: GEN_SUBEVENTNAME_CODE\n  applies_to: {}\n  primitive: code_membership\n"
        "  target: './/*[@SubEventName]'\n  attribute: SubEventName\n"
        "  params: {codeset: EVENT_UNIT, field: ENG_shortDescription, code_attr: Unit}\n"
        "  severity: warning\n  scope: message\n  source_ref: gen\n", encoding="utf-8")
    swm = tmp_path / "swm.yaml"
    swm.write_text(
        "- id: SWM_SUBEVENTNAME_CODE\n  applies_to: {disciplines: [SWM]}\n  primitive: code_membership\n"
        "  target: './/*[@SubEventName]'\n  attribute: SubEventName\n"
        "  params: {codeset: EVENT_UNIT, field: ENG_Description, code_attr: Unit}\n"
        "  severity: warning\n  scope: message\n  source_ref: swm\n", encoding="utf-8")

    rules, errors, conflicts, deduped, _spec = load_rule_defs([swm, gen])

    assert {r.id for r in rules} == {"GEN_SUBEVENTNAME_CODE", "SWM_SUBEVENTNAME_CODE"}
    assert conflicts == []


def test_value_format_rules_with_different_regex_are_not_duplicates(tmp_path):
    # Both rules check @Code on the same target but enforce different patterns,
    # so they emit different findings. The semantic key must see the regex or
    # one rule is silently dropped and its check never runs.
    a = tmp_path / "a.yaml"
    a.write_text(
        "- id: A_CODE_DIGITS\n  applies_to: {}\n  primitive: value_format\n"
        "  target: './/Competitor'\n  attribute: Code\n"
        "  params: {regex: '^[0-9]{3}$'}\n"
        "  severity: error\n  scope: message\n  source_ref: a\n", encoding="utf-8")
    b = tmp_path / "b.yaml"
    b.write_text(
        "- id: B_CODE_ALPHA\n  applies_to: {}\n  primitive: value_format\n"
        "  target: './/Competitor'\n  attribute: Code\n"
        "  params: {regex: '^[A-Z]{3}$'}\n"
        "  severity: error\n  scope: message\n  source_ref: b\n", encoding="utf-8")

    rules, errors, conflicts, deduped, _spec = load_rule_defs([a, b])

    assert {r.id for r in rules} == {"A_CODE_DIGITS", "B_CODE_ALPHA"}
    assert conflicts == []


def test_conditional_presence_rules_with_different_conditions_are_not_duplicates(tmp_path):
    # Same target, different trigger and different consequence. Dropping either
    # would silently disable a documented check.
    a = tmp_path / "a.yaml"
    a.write_text(
        "- id: A_TBD_FORBIDS_CHILD\n  applies_to: {}\n  primitive: conditional_presence\n"
        "  target: './/Competitor'\n"
        "  params: {when_attr: Code, when_equals: TBD, forbid_child: Composition}\n"
        "  severity: error\n  scope: message\n  source_ref: a\n", encoding="utf-8")
    b = tmp_path / "b.yaml"
    b.write_text(
        "- id: B_ANY_REQUIRES_ORDER\n  applies_to: {}\n  primitive: conditional_presence\n"
        "  target: './/Competitor'\n"
        "  params: {when_attr: Code, when_equals: '*', require: Order}\n"
        "  severity: error\n  scope: message\n  source_ref: b\n", encoding="utf-8")

    rules, errors, conflicts, deduped, _spec = load_rule_defs([a, b])

    assert {r.id for r in rules} == {"A_TBD_FORBIDS_CHILD", "B_ANY_REQUIRES_ORDER"}
    assert conflicts == []


def test_code_membership_rules_with_different_allow_lists_are_not_duplicates(tmp_path):
    # `allow` whitelists documented sentinels (e.g. TBD) per rule. A global rule
    # without the sentinel does NOT cover a discipline rule that permits it --
    # keeping only the global one would raise false positives on legal TBD values.
    gen = tmp_path / "gen.yaml"
    gen.write_text(
        "- id: GEN_VENUE_CODE\n  applies_to: {}\n  primitive: code_membership\n"
        "  target: './/*[@Venue]'\n  attribute: Venue\n"
        "  params: {codeset: VENUE}\n"
        "  severity: warning\n  scope: message\n  source_ref: gen\n", encoding="utf-8")
    arc = tmp_path / "arc.yaml"
    arc.write_text(
        "- id: ARC_VENUE_CODE\n  applies_to: {disciplines: [ARC]}\n  primitive: code_membership\n"
        "  target: './/*[@Venue]'\n  attribute: Venue\n"
        "  params: {codeset: VENUE, allow: [TBD]}\n"
        "  severity: warning\n  scope: message\n  source_ref: arc\n", encoding="utf-8")

    rules, errors, conflicts, deduped, _spec = load_rule_defs([arc, gen])

    assert {r.id for r in rules} == {"GEN_VENUE_CODE", "ARC_VENUE_CODE"}
    assert conflicts == []


def test_identical_params_still_dedupe(tmp_path):
    # Guard the other direction: making the key param-aware must not weaken the
    # dedup that collapsed 503 loaded rules to 99. Byte-identical params on a
    # global and a discipline rule are still one check -> discipline copy drops.
    gen = tmp_path / "gen.yaml"
    gen.write_text(
        "- id: GEN_VERSION_POSINT\n  applies_to: {}\n  primitive: value_format\n"
        "  target: './/*[@Version]'\n  attribute: Version\n"
        "  params: {regex: '^[0-9]+$'}\n"
        "  severity: error\n  scope: message\n  source_ref: gen\n", encoding="utf-8")
    ath = tmp_path / "ath.yaml"
    ath.write_text(
        "- id: ATH_VERSION_POSINT\n  applies_to: {disciplines: [ATH]}\n  primitive: value_format\n"
        "  target: './/*[@Version]'\n  attribute: Version\n"
        "  params: {regex: '^[0-9]+$'}\n"
        "  severity: error\n  scope: message\n  source_ref: ath\n", encoding="utf-8")

    rules, errors, conflicts, deduped, _spec = load_rule_defs([ath, gen])

    assert [r.id for r in rules] == ["GEN_VERSION_POSINT"]
    assert conflicts == []
    assert any("ATH_VERSION_POSINT" in d for d in deduped)


def test_pack_rules_cannot_use_core_prefix(tmp_path):
    f = tmp_path / "sneaky.yaml"
    f.write_text(
        "- id: CORE_NO_EMPTY_ATTRS\n  primitive: value_format\n  target: '.'\n"
        "  attribute: X\n  params: {regex: '.*'}\n"
        "- id: OK_RULE\n  primitive: value_format\n  target: '.'\n"
        "  attribute: X\n  params: {regex: '.*'}\n",
        encoding="utf-8")
    rules, errors, _, _, _ = load_rule_defs([f])
    assert [r.id for r in rules] == ["OK_RULE"]
    assert any("CORE_" in e and "reserved" in e for e in errors)
