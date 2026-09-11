from __future__ import annotations
import pathlib

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
PACKAGES = ("odf_validator", "api")


def _python_files():
    for package in PACKAGES:
        for path in sorted((PROJECT_ROOT / package).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            yield path


def _unencodable_constants(code):
    """Every str constant in this code object, or nested in one, that cannot
    be encoded as UTF-8."""
    for const in code.co_consts:
        if isinstance(const, str):
            try:
                const.encode("utf-8")
            except UnicodeEncodeError:
                yield const
        elif hasattr(const, "co_consts"):
            yield from _unencodable_constants(const)


@pytest.mark.parametrize("path", list(_python_files()),
                         ids=lambda p: str(p.relative_to(PROJECT_ROOT)))
def test_every_string_constant_survives_utf8_encoding(path):
    """A module whose compiled constants hold an unpaired surrogate cannot be
    imported on every Python, and the failure is a startup crash rather than
    anything the code does.

    This is not hypothetical. `_confined`'s docstring in sources/sync.py once
    documented the surrogate case by writing a live '\\ud800' escape, which
    compiles to a real unpaired surrogate inside the docstring constant. On
    CPython 3.10 marshal writes that to a .pyc using surrogatepass and nothing
    complains -- the entire test suite passed. On CPython 3.14 the same
    constant is encoded as plain UTF-8 while caching the module, which raises

        UnicodeEncodeError: 'utf-8' codec can't encode character '\\ud800'
        in position 3439: surrogates not allowed

    from inside the import machinery, before a single line of the module runs.
    The app would not start at all.

    A docstring should DESCRIBE such a character, never CONTAIN it: write the
    escape with a doubled backslash so the text reads '\\ud800' and the
    constant stays encodable. This test is parametrized per file so a failure
    names the offending module directly.
    """
    source = path.read_text(encoding="utf-8")
    code = compile(source, str(path), "exec")

    offenders = list(_unencodable_constants(code))

    assert not offenders, (
        f"{path.relative_to(PROJECT_ROOT)} compiles to {len(offenders)} string "
        f"constant(s) that cannot be encoded as UTF-8, which breaks importing "
        f"it on some CPython versions. First offender begins: "
        f"{offenders[0][:80]!a}"
    )
