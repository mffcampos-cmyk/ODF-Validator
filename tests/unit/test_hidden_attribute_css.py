"""The [hidden] attribute must win over component display rules.

app.js hides elements exclusively via `.hidden = true` (the DOM-light
constraint documented at the top of app.js forbids classList). Any component
rule that sets `display` defeats the UA's `[hidden] { display: none }`,
because an author declaration outranks a UA one. That is what kept the idle
plate painted over the tally bar forever. Raised as U-C1.
"""
import re
from pathlib import Path

CSS = Path(__file__).resolve().parents[2] / "web" / "static" / "styles.css"


def test_stylesheet_defeats_display_rules_for_hidden_elements():
    css = CSS.read_text(encoding="utf-8")
    assert re.search(r"\[hidden\]\s*\{[^}]*display\s*:\s*none\s*!important",
                     css), (
        "styles.css must contain [hidden] { display: none !important; } — "
        "without it any component `display` rule keeps a .hidden element "
        "painted (e.g. .tally-idle covering the tally bar).")


def test_the_idle_plate_still_sets_display_flex():
    """Pins the reason the rule is needed.

    If .tally-idle ever stops setting `display`, the !important override
    becomes dead weight and should be reconsidered rather than left as
    unexplained cargo.
    """
    css = CSS.read_text(encoding="utf-8")
    idle = css[css.index(".tally-idle"):]
    assert "display: flex" in idle[:idle.index("}")]
