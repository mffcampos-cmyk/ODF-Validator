from __future__ import annotations
import os
import threading
import webbrowser

DISABLE_ENV = "ODF_NO_BROWSER"   # set to disable auto-open (e.g. on a server)
URL_ENV = "ODF_OPEN_URL"         # override the URL that is opened


def default_url(env: dict | None = None) -> str:
    env = os.environ if env is None else env
    return env.get(URL_ENV) or "http://127.0.0.1:8000/"


def open_browser(url: str, opener=webbrowser.open, env: dict | None = None) -> bool:
    """Open `url` in the default browser. Returns False (and does nothing) when
    auto-open is disabled via the ODF_NO_BROWSER environment variable."""
    env = os.environ if env is None else env
    if str(env.get(DISABLE_ENV, "")).strip():
        return False
    opener(url)
    return True


def schedule_open(url: str | None = None, delay: float = 1.0,
                  opener=webbrowser.open, env: dict | None = None) -> None:
    """Open the browser shortly after startup (delay lets the server bind first).
    No-op when ODF_NO_BROWSER is set. Failures are swallowed so a missing browser
    never crashes the server."""
    env = os.environ if env is None else env
    if str(env.get(DISABLE_ENV, "")).strip():
        return
    target = url or default_url(env)

    def _go():
        try:
            open_browser(target, opener=opener, env=env)
        except Exception:
            pass

    t = threading.Timer(delay, _go)
    t.daemon = True
    t.start()
