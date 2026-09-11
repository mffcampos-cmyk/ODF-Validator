from odf_validator.loader.pack import RulePack, LoadReport, ruleset_summary


def _pack(name, version, disciplines, rule_count=0, error_count=0, cache_warning_count=0):
    report = LoadReport(errors=["e"] * error_count,
                         cache_warnings=["c"] * cache_warning_count)
    return RulePack(name=name, version=version, xsd_paths=[], root_xsd=None,
                     schema=None, codes=None, rules=list(range(rule_count)),
                     disciplines=disciplines, report=report)


def test_summarizes_name_version_disciplines_and_counts():
    packs = {"SYOG26": _pack("SYOG26", "1.9.1", ["ARC", "GEN"], rule_count=4, error_count=0)}

    summary = ruleset_summary(packs)

    assert summary == [{
        "name": "SYOG26",
        "version": "1.9.1",
        "disciplines": ["ARC", "GEN"],
        "rule_count": 4,
        "error_count": 0,
        "cache_warning_count": 0,
    }]


def test_ruleset_with_no_disciplines_reports_empty_list():
    packs = {"BARE": _pack("BARE", "", [], rule_count=0, error_count=0)}

    summary = ruleset_summary(packs)

    assert summary[0]["disciplines"] == []


def test_multiple_rulesets_are_sorted_by_name():
    packs = {
        "ZULU": _pack("ZULU", "1", ["ARC"]),
        "ALPHA": _pack("ALPHA", "1", ["GEN"]),
    }

    summary = ruleset_summary(packs)

    assert [s["name"] for s in summary] == ["ALPHA", "ZULU"]


def test_error_count_reflects_report_errors():
    packs = {"SYOG26": _pack("SYOG26", "1", ["ARC"], error_count=3)}

    summary = ruleset_summary(packs)

    assert summary[0]["error_count"] == 3


def test_cache_warning_count_is_separate_from_error_count():
    # A cache-integrity problem is not a rule-load failure: /rulesets must be
    # able to tell the two apart rather than folding one into the other.
    packs = {"SYOG26": _pack("SYOG26", "1", ["ARC"], error_count=0, cache_warning_count=2)}

    summary = ruleset_summary(packs)

    assert summary[0]["cache_warning_count"] == 2
    assert summary[0]["error_count"] == 0


def test_empty_packs_returns_empty_list():
    assert ruleset_summary({}) == []
