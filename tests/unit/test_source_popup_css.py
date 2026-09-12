"""The import popup's three tones must exist in the stylesheet.

The popup reports three outcomes: red for a failure, yellow for warnings,
green for a clean import. Green is a DEPARTURE from the stylesheet's own rule
that the only saturated colours are severities, so it gets its own token and
its own reason written down rather than borrowing --info or a hard-coded hex.
"""
import re
from pathlib import Path

CSS = Path(__file__).resolve().parents[2] / "web" / "static" / "styles.css"


def _block(css: str, selector: str) -> str:
    start = css.index(selector)
    return css[start:css.index("}", start)]


def test_the_three_tones_are_defined():
    css = CSS.read_text(encoding="utf-8")
    for selector in (".popup-fail", ".popup-warn", ".popup-ok"):
        assert selector in css, f"{selector} is not styled"


def test_each_tone_uses_its_own_signal_colour():
    css = CSS.read_text(encoding="utf-8")
    assert "--error" in _block(css, ".popup-fail")
    assert "--warning" in _block(css, ".popup-warn")
    assert "--ok" in _block(css, ".popup-ok"), (
        "success needs its own token; the severity palette has no green")


def test_the_success_token_is_declared_on_root():
    css = CSS.read_text(encoding="utf-8")
    root = _block(css, ":root")
    assert re.search(r"--ok:\s*#", root), "--ok must be a declared token"
    assert re.search(r"--ok-tint:\s*#", root)


def test_the_popup_does_not_defeat_the_hidden_attribute():
    """The host is hidden with .hidden = true, so its own display rule must
    sit behind [hidden] { display: none !important } — which
    test_hidden_attribute_css pins."""
    css = CSS.read_text(encoding="utf-8")
    assert "display" in _block(css, ".popup {"), (
        "if .popup ever stops setting display, this pairing needs rethinking"
    )


def test_a_busy_button_is_visibly_busy_whatever_its_variant():
    """sources.js sets aria-busy on every button in the form it submits, and
    the apply button is a plain .btn -- so the busy style cannot live on
    .btn-run alone or that button changes not at all while it waits."""
    css = CSS.read_text(encoding="utf-8")
    assert re.search(r"\.btn\[aria-busy=\"true\"\]", css), (
        'styles.css needs a .btn[aria-busy="true"] rule; .btn-run only '
        "covers the primary variant")
