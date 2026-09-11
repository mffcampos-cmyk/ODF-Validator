"""Run the tests/js suite under pytest.

The JS tests exercise web/static/app.js against a hand-rolled document stub,
which is the only automated guard on the DOM-light constraint documented at
the top of app.js. Until now nothing ran them: there is no package.json and
no CI, so a regression in validate() (see the 2026-08-26 audit) slipped past
a stub that was sitting right there.
"""
from __future__ import annotations
import shutil
import subprocess
from pathlib import Path

import pytest

JS_DIR = Path(__file__).resolve().parent.parent / "js"
JS_TESTS = sorted(JS_DIR.glob("*.test.js"))


@pytest.mark.parametrize("js_file", JS_TESTS, ids=lambda p: p.name)
def test_js_suite(js_file: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; JS suite not run")
    proc = subprocess.run([node, str(js_file)], capture_output=True, text=True)
    assert proc.returncode == 0, f"{js_file.name} failed:\n{proc.stdout}{proc.stderr}"


def test_js_suite_is_not_empty() -> None:
    # Guards against the parametrize list silently going empty if the
    # directory is moved or the naming convention changes.
    assert JS_TESTS, f"no *.test.js files found under {JS_DIR}"
