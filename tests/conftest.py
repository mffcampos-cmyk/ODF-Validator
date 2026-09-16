import pathlib

import pytest

import api.app as app_module

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent


def ruleset_is_populated(root: pathlib.Path = PROJECT_ROOT) -> bool:
    """True when the IOC source documents have been imported.

    The published repository ships the authored rules and the SYOG26 schema
    (a clone could re-download it, but the published copy does not compile),
    and never the IOC documents that are re-downloadable and fetched on first
    launch: the Common Codes workbook and the Data Dictionaries. Tests that
    load the real code tables or the DD obligations cannot run until that
    import has happened.

    Keyed on those documents, not on the schema. Keying on the XSDs was right
    until the schema shipped; after that the guard stopped skipping anything,
    and fifty pack-dependent tests ran red on a fresh public clone.
    """
    pack = root / "Rules" / "SYOG26"
    try:
        has_codes = any(p.suffix.lower() == ".xlsx"
                        for p in (pack / "codes").iterdir())
        has_dd = any(
            p.suffix.lower() in (".pdf", ".md", ".docx")
            and "Data_Dictionary" in p.name
            for disc in (pack / "Disciplines").iterdir() if disc.is_dir()
            for p in disc.iterdir())
    except OSError:
        return False
    return has_codes and has_dd


needs_populated_ruleset = pytest.mark.skipif(
    not ruleset_is_populated(),
    reason="needs the IOC source documents; run the first-launch import "
           "(Rulesets -> check and download updates -> apply)")


@pytest.fixture(autouse=True, scope="session")
def allow_testclient_host():
    """Let the Starlette TestClient through the loopback-Host check.

    enforce_local_host rejects any Host that isn't a loopback name, which is
    what closes the DNS-rebinding path (a security review, finding F-02). TestClient
    sends Host: testserver, so without this the whole integration suite 400s.

    Widening the allowlist here rather than in api.app keeps the shipped
    default honest -- production allows only real loopback names. 'testserver'
    is not a resolvable public name, so an attacker has no way to make a
    victim's browser send it even if this fixture somehow ran in production.
    """
    app_module.ALLOWED_HOSTS.add("testserver")
    yield
    app_module.ALLOWED_HOSTS.discard("testserver")
