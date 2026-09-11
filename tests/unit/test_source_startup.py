from __future__ import annotations

import pytest

from odf_validator.sources import sync


def test_startup_refresh_survives_a_failing_check(monkeypatch):
    """A failing check must not take startup down -- and must not vanish.

    This test used to assert SOURCE_REPORTS stayed EMPTY after a crash, which
    encoded the original swallow-it-silently behaviour. That behaviour was the
    reason a total outage went unnoticed: the failure was logged at INFO to an
    unconfigured logger (so it never printed) and stored nowhere, leaving
    /sources to synthesise a healthy-looking empty report. The surviving
    requirement is that refresh_source_reports does not raise; the failure is
    now additionally required to be recorded.
    """
    from api import app as app_module

    def boom(ruleset_dir, **kwargs):
        raise RuntimeError("network is on fire")

    monkeypatch.setattr(app_module, "source_check", boom)
    app_module.SOURCE_REPORTS.clear()

    app_module.refresh_source_reports()      # must not raise

    report = app_module.SOURCE_REPORTS.get("SYOG26")
    assert report is not None, (
        "the crash must be recorded, or the UI cannot distinguish it from a "
        "check that simply has not run yet")
    assert "network is on fire" in report.error
    assert report.configured is True


def test_check_on_start_false_skips_the_pack(tmp_path, monkeypatch):
    from api import app as app_module

    root = tmp_path / "SYOG26"
    root.mkdir()
    (root / "pack.yaml").write_text(
        'version: "t"\n'
        'source:\n'
        '  index_url: https://odf.olympictech.org/x.html\n'
        '  check_on_start: false\n', encoding="utf-8")

    called = []
    monkeypatch.setattr(app_module, "source_check",
                        lambda d, **k: called.append(d))
    monkeypatch.setattr(app_module, "RULES_ROOT", tmp_path)
    app_module.SOURCE_REPORTS.clear()

    app_module.refresh_source_reports()
    assert called == []


def test_solg28_manifest_has_no_source_block():
    """The LA2028 page does not exist yet; adding index_url later is the whole
    change needed."""
    from pathlib import Path
    import yaml

    root = Path(__file__).resolve().parents[2] / "Rules" / "SOLG28"
    manifest = yaml.safe_load((root / "pack.yaml").read_text(encoding="utf-8"))
    assert "source" not in (manifest or {})
    assert sync.read_source_config(root) == {}
