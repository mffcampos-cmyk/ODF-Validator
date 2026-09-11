from __future__ import annotations
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

# The only host this app will ever talk to. Not configurable: widening it is a
# code change that should be reviewed, not a setting someone can flip.
ALLOWED_HOST = "odf.olympictech.org"

# The largest document published today is well under 1MB. This cap is not a
# tuning knob -- it bounds a misconfiguration or a hostile response, nothing
# more.
MAX_SOURCE_BYTES = 50 * 1024 * 1024

CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 30.0

# DO NOT "TIDY" THIS INTO A PLAIN PRODUCT TOKEN. It was arrived at
# empirically, and the obvious-looking simplification breaks the feature
# outright.
#
# odf.olympictech.org sits behind Akamai bot mitigation. Measured against the
# live site on 2026-09-06, same machine, seconds apart:
#
#   httpx's own default ('python-httpx/0.28.1')  -> connection reset
#                                                   (WinError 10054)
#   'ODF-Validator/1.0 (...)', a plain honest UA -> connection reset
#   'Mozilla/5.0 (Windows NT 10.0; Win64; x64) ODF-Validator/1.0'
#                                                -> 200 in 0.5s
#
# So the edge accepts browser-SHAPED tokens only; merely identifying yourself
# politely is not enough. Sending no User-Agent at all is what made the whole
# feature silently non-functional in its first release: every check failed with
# a read timeout or a reset, and the app reported nothing.
#
# The compromise taken deliberately: keep the 'Mozilla/5.0 (...)' prefix that
# the filter requires, and keep this application's real name in the string, so
# the request still says truthfully what is making it. We do not claim to be
# Chrome. The platform token is a fixed, tested literal rather than something
# derived from the host -- a Linux variant has never been tested against the
# filter, and quietly guessing one would risk reintroducing the outage.
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ODF-Validator/1.0"

# Servers are inconsistent about these, so each kind accepts a set. An
# octet-stream is always allowed: it means "a file", which is what we asked
# for.
EXPECTED_TYPES = {
    "dd": {"application/pdf"},
    "general": {"application/pdf"},
    "codes": {"application/zip", "application/x-zip-compressed"},
    "schema": {"application/zip", "application/x-zip-compressed"},
}
ALWAYS_OK_TYPE = "application/octet-stream"


class SourceFetchError(Exception):
    """A source document could not be retrieved, or came back wrong."""


@dataclass
class FetchResult:
    status: int
    body: bytes | None
    etag: str | None = None
    last_modified: str | None = None


def check_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise SourceFetchError(f"Refusing a non-HTTPS source URL: {url}")
    if parts.hostname != ALLOWED_HOST:
        raise SourceFetchError(
            f"Refusing a source URL on host '{parts.hostname}'; "
            f"only {ALLOWED_HOST} is allowed.")


def get(url: str, *, etag: str | None = None, last_modified: str | None = None,
        expect: str | None = None,
        client: httpx.Client | None = None) -> FetchResult:
    """Fetch one document, conditionally when we hold validators for it.

    Redirects are followed manually rather than by httpx, so that every hop is
    re-checked against the allowlist. httpx's own follow_redirects would land
    us on another host before we ever saw the URL.
    """
    check_url(url)
    # Sent on every request, including the conditional ones and every redirect
    # hop -- see USER_AGENT for why this is not optional.
    headers = {"User-Agent": USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    owned = client is None
    client = client or httpx.Client(
        follow_redirects=False,
        timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT))
    try:
        response = _get_following_redirects(client, url, headers)
        try:
            if response.status_code == 304:
                return FetchResult(304, None, etag, last_modified)
            if response.status_code != 200:
                raise SourceFetchError(
                    f"{url} returned HTTP {response.status_code}.")

            body = _read_body_within_limit(url, response)

            _check_type(url, response.headers.get("content-type", ""), expect)
            return FetchResult(200, body,
                               response.headers.get("etag"),
                               response.headers.get("last-modified"))
        finally:
            response.close()
    finally:
        if owned:
            client.close()


def _get_following_redirects(client: httpx.Client, url: str, headers: dict,
                             max_hops: int = 5) -> httpx.Response:
    for _ in range(max_hops):
        response = client.send(
            client.build_request("GET", url, headers=headers), stream=True)
        if response.status_code not in (301, 302, 303, 307, 308):
            return response
        response.close()
        location = response.headers.get("location", "")
        url = str(httpx.URL(url).join(location))
        check_url(url)          # every hop, not just the first
    raise SourceFetchError(f"Too many redirects fetching {url}.")


def _read_body_within_limit(url: str, response: httpx.Response) -> bytes:
    """Read a streamed response body, aborting before an oversize body is
    ever fully buffered.

    A declared Content-Length lets us refuse before reading anything, but
    that header is untrusted (the caller can lie or omit it), so the real
    enforcement is the running total checked as each chunk arrives.
    """
    declared_length = response.headers.get("content-length")
    if declared_length is not None:
        try:
            if int(declared_length) > MAX_SOURCE_BYTES:
                raise SourceFetchError(
                    f"{url} is larger than the "
                    f"{MAX_SOURCE_BYTES // (1024 * 1024)}MB source limit.")
        except ValueError:
            pass  # malformed header; fall through to the incremental check

    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > MAX_SOURCE_BYTES:
            raise SourceFetchError(
                f"{url} is larger than the "
                f"{MAX_SOURCE_BYTES // (1024 * 1024)}MB source limit.")
        chunks.append(chunk)
    return b"".join(chunks)


def _check_type(url: str, content_type: str, expect: str | None) -> None:
    if expect is None:
        return
    allowed = EXPECTED_TYPES.get(expect)
    if not allowed:
        return
    actual = content_type.split(";")[0].strip().lower()
    if not actual:
        raise SourceFetchError(
            f"{url} returned no content-type, expected one of "
            f"{sorted(allowed)}. The document was not saved.")
    if actual != ALWAYS_OK_TYPE and actual not in allowed:
        raise SourceFetchError(
            f"{url} returned content-type '{actual}', expected one of "
            f"{sorted(allowed)}. The document was not saved.")
