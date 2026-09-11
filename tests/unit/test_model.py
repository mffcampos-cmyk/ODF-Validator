from odf_validator.model import Severity, Layer, Finding, Location, RunResult


def make_finding(sev):
    return Finding(severity=sev, layer=Layer.CODE, rule_id="R1",
                   message="msg", location=Location(line=3, path="/OdfBody"))


def make_finding_at(line, path, rule_id="R1", message="msg", sev=Severity.ERROR,
                    source_ref=""):
    return Finding(severity=sev, layer=Layer.CODE, rule_id=rule_id,
                   message=message, location=Location(line=line, path=path),
                   source_ref=source_ref)


def test_runresult_counts_and_serialization():
    r = RunResult(doc_type="DT_RESULT", discipline="ARC", document_code="ARC...",
                  version=1, pack_name="SYOG26",
                  findings=[make_finding(Severity.ERROR), make_finding(Severity.WARNING),
                            make_finding(Severity.ERROR)])
    assert r.counts() == {"error": 2, "warning": 1, "info": 0}
    d = r.to_dict()
    assert d["doc_type"] == "DT_RESULT"
    assert d["findings"][0]["severity"] == "error"
    assert d["findings"][0]["location"]["line"] == 3


def _rr(findings):
    return RunResult(doc_type="DT", discipline="ARC", document_code="ARC",
                     version=1, pack_name="SYOG26", findings=findings)


def test_identical_findings_fold_into_one_entry():
    # 3 findings identical except location -> one grouped entry.
    r = _rr([make_finding_at(4, "/OdfBody/Competition/Team[1]"),
             make_finding_at(7, "/OdfBody/Competition/Team[2]"),
             make_finding_at(10, "/OdfBody/Competition/Team[3]")])
    d = r.to_dict()
    assert len(d["findings"]) == 1
    g = d["findings"][0]
    assert g["occurrences"] == 3
    # first occurrence stays as the primary location (back-compat)
    assert g["location"] == {"line": 4, "path": "/OdfBody/Competition/Team[1]"}
    # every place the error appears is listed, in first-seen order
    assert g["locations"] == [
        {"line": 4, "path": "/OdfBody/Competition/Team[1]"},
        {"line": 7, "path": "/OdfBody/Competition/Team[2]"},
        {"line": 10, "path": "/OdfBody/Competition/Team[3]"},
    ]


def test_distinct_messages_are_not_folded():
    # Same rule but different message text (different bad value) stay separate.
    r = _rr([make_finding_at(4, "/a", message="@TeamType='' is invalid"),
             make_finding_at(7, "/b", message="@TeamType='X' is invalid")])
    d = r.to_dict()
    assert len(d["findings"]) == 2


def test_grouping_preserves_first_seen_order_and_true_counts():
    r = _rr([make_finding_at(1, "/a", rule_id="R1", message="m1"),
             make_finding_at(2, "/b", rule_id="R2", message="m2"),
             make_finding_at(3, "/c", rule_id="R1", message="m1")])
    # counts reflect the true, ungrouped total
    assert r.counts() == {"error": 3, "warning": 0, "info": 0}
    d = r.to_dict()
    assert [g["rule_id"] for g in d["findings"]] == ["R1", "R2"]
    assert d["findings"][0]["occurrences"] == 2
    # sum of occurrences equals the true error total
    assert sum(g["occurrences"] for g in d["findings"]) == 3


def test_singleton_finding_reports_one_occurrence_and_one_location():
    r = _rr([make_finding_at(5, "/x")])
    g = r.to_dict()["findings"][0]
    assert g["occurrences"] == 1
    assert g["locations"] == [{"line": 5, "path": "/x"}]


def test_cap_applies_to_groups_not_raw_findings():
    # 20 identical findings collapse to 1 group; a cap of 1 keeps that group
    # and omits nothing, even though 20 raw findings existed.
    r = _rr([make_finding_at(i, f"/Team[{i}]") for i in range(20)])
    d = r.to_dict(max_findings=1)
    assert len(d["findings"]) == 1
    assert d["findings"][0]["occurrences"] == 20
    assert d["findings_omitted"] == 0


def test_cap_counts_omitted_groups():
    # 3 distinct rules -> 3 groups; cap of 2 omits exactly one group.
    r = _rr([make_finding_at(1, "/a", rule_id="R1", message="m1"),
             make_finding_at(2, "/b", rule_id="R2", message="m2"),
             make_finding_at(3, "/c", rule_id="R3", message="m3")])
    d = r.to_dict(max_findings=2)
    assert len(d["findings"]) == 2
    assert d["findings_omitted"] == 1
