from api.browser import default_url, open_browser


def test_default_url_is_localhost_8000():
    assert default_url(env={}) == "http://127.0.0.1:8000/"


def test_default_url_env_override():
    assert default_url(env={"ODF_OPEN_URL": "http://0.0.0.0:9000/"}) == "http://0.0.0.0:9000/"


def test_open_browser_invokes_opener():
    calls = []
    ok = open_browser("http://x/", opener=calls.append, env={})
    assert ok is True and calls == ["http://x/"]


def test_open_browser_disabled_by_env():
    calls = []
    ok = open_browser("http://x/", opener=calls.append, env={"ODF_NO_BROWSER": "1"})
    assert ok is False and calls == []
