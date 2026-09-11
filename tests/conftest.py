import pathlib

import pytest

import api.app as app_module

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent


def ruleset_is_populated() -> bool:
    """True when the IOC source documents have been imported.

    The published repository ships the authored rules but not the IOC
    documents, which are re-downloadable and are fetched on first launch.
    Tests that load a compiled schema or the real code tables cannot run
    until that import has happened.
    """
    xsd_dir = PROJECT_ROOT / "Rules" / "SYOG26" / "xsd"
    try:
        return any(p.suffix.lower() == ".xsd" for p in xsd_dir.iterdir())
    except OSError:
        return False


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
