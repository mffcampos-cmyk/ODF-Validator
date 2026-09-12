"""Static assets must be revalidated, not cached blind.

The import popup shipped with its CSS and rendered as unstyled text in the
operator's browser (2026-09-12). The server was serving the new stylesheet
correctly; Chrome never asked for it. StaticFiles sends ETag and
Last-Modified but no Cache-Control, and with no Cache-Control a browser is
free to apply heuristic freshness -- roughly a tenth of the file's age at the
time it was cached. styles.css had sat unchanged for weeks, so the copy taken
then stayed "fresh" for days.

The tell was which files DID update: rulesets.html is rendered per request and
sources.js was a brand-new URL, so both were current, while styles.css and
app.js -- old URLs with old Last-Modified dates -- were not. A change can
therefore appear to half-work, which is worse than not working.

This is a single-operator tool on loopback. Revalidating every asset costs one
304 and removes the whole class of "it works for me after a hard refresh".
"""
from fastapi.testclient import TestClient
from api.app import app

client = TestClient(app)


def test_static_assets_are_served_with_no_cache():
    r = client.get("/static/styles.css")

    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-cache", (
        "without an explicit Cache-Control a browser may serve a stale "
        "stylesheet for days after an update")


def test_the_asset_still_carries_a_validator_so_revalidation_is_cheap():
    """no-cache means "ask first", not "send it all again": the ETag is what
    turns the question into a 304."""
    r = client.get("/static/app.js")

    assert r.status_code == 200
    assert r.headers.get("etag"), r.headers
