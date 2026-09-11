from __future__ import annotations

import httpx
import pytest

from odf_validator.sources.fetch import (MAX_SOURCE_BYTES, SourceFetchError,
                                         check_url, get)

URL = "https://odf.olympictech.org/2026-Dakar/YOG/ODF_SWM_Data_Dictionary.pdf"


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler),
                        follow_redirects=False)


def test_plain_200_returns_body_and_validators():
    def handler(request):
        return httpx.Response(200, content=b"%PDF-1.7 body",
                              headers={"etag": '"e1"',
                                       "content-type": "application/pdf"})

    with client_for(handler) as c:
        result = get(URL, expect="dd", client=c)
    assert result.status == 200
    assert result.body == b"%PDF-1.7 body"
    assert result.etag == '"e1"'


def test_stored_validators_are_sent_as_conditional_headers():
    seen = {}

    def handler(request):
        seen.update(request.headers)
        return httpx.Response(304)

    with client_for(handler) as c:
        result = get(URL, etag='"e1"', last_modified="Wed, 02 Sep 2026 09:14:00 GMT",
                     client=c)
    assert seen["if-none-match"] == '"e1"'
    assert seen["if-modified-since"] == "Wed, 02 Sep 2026 09:14:00 GMT"
    assert result.status == 304
    assert result.body is None


def test_redirect_within_the_allowlisted_host_is_followed():
    def handler(request):
        if request.url.path.endswith("old.pdf"):
            return httpx.Response(
                302, headers={"location": "https://odf.olympictech.org/new.pdf"})
        return httpx.Response(200, content=b"%PDF-1.7",
                              headers={"content-type": "application/pdf"})

    with client_for(handler) as c:
        result = get("https://odf.olympictech.org/old.pdf", expect="dd", client=c)
    assert result.body == b"%PDF-1.7"


def test_redirect_off_the_allowlisted_host_is_refused():
    def handler(request):
        return httpx.Response(302, headers={"location": "https://evil.example/x.pdf"})

    with client_for(handler) as c:
        with pytest.raises(SourceFetchError, match="host"):
            get("https://odf.olympictech.org/old.pdf", client=c)


def test_non_allowlisted_url_is_refused_without_any_request():
    with pytest.raises(SourceFetchError, match="host"):
        check_url("https://evil.example/2026-Dakar/x.pdf")


def test_plain_http_is_refused():
    with pytest.raises(SourceFetchError, match="HTTPS"):
        check_url("http://odf.olympictech.org/x.pdf")


def test_oversize_body_is_refused():
    def handler(request):
        return httpx.Response(200, content=b"x" * (MAX_SOURCE_BYTES + 1),
                              headers={"content-type": "application/pdf"})

    with client_for(handler) as c:
        with pytest.raises(SourceFetchError, match="larger than"):
            get(URL, expect="dd", client=c)


class _CountingByteStream(httpx.SyncByteStream):
    """A response body that yields chunks and records how many were pulled,
    so a test can prove the body was abandoned early rather than fully
    buffered before the size check ran."""

    def __init__(self, total_size: int, chunk_size: int = 1024 * 1024):
        self.total_size = total_size
        self.chunk_size = chunk_size
        self.chunks_pulled = 0

    def __iter__(self):
        remaining = self.total_size
        while remaining > 0:
            n = min(self.chunk_size, remaining)
            self.chunks_pulled += 1
            remaining -= n
            yield b"x" * n


def test_oversize_body_is_streamed_not_fully_buffered():
    # A body far over the cap: if get() called client.get(...) (or otherwise
    # read the whole stream before checking length), every chunk would be
    # pulled before the error could even be raised. Streaming must abort
    # partway through.
    total_size = MAX_SOURCE_BYTES + 10 * 1024 * 1024
    stream = _CountingByteStream(total_size)

    def handler(request):
        return httpx.Response(200, headers={"content-type": "application/pdf"},
                              stream=stream)

    with client_for(handler) as c:
        with pytest.raises(SourceFetchError, match="larger than"):
            get(URL, expect="dd", client=c)

    max_expected_chunks = (MAX_SOURCE_BYTES // stream.chunk_size) + 2
    assert stream.chunks_pulled <= max_expected_chunks, (
        f"pulled {stream.chunks_pulled} chunks out of a possible "
        f"{-(-total_size // stream.chunk_size)}; the oversize body was "
        "fully buffered instead of being aborted early")


def test_content_type_mismatch_is_refused():
    def handler(request):
        return httpx.Response(200, content=b"<html>404</html>",
                              headers={"content-type": "text/html"})

    with client_for(handler) as c:
        with pytest.raises(SourceFetchError, match="content-type"):
            get(URL, expect="dd", client=c)


def test_missing_content_type_is_refused_when_a_type_is_expected():
    # No content-type header at all -- e.g. an HTML error page served
    # without one -- must not silently pass as the expected PDF/zip type.
    def handler(request):
        return httpx.Response(200, content=b"<html>not really a pdf</html>")

    with client_for(handler) as c:
        with pytest.raises(SourceFetchError, match="content-type"):
            get(URL, expect="dd", client=c)


def test_missing_content_type_is_still_fine_when_no_type_is_expected():
    # expect=None (used for the index page) must keep skipping the check
    # entirely, missing header or not.
    def handler(request):
        return httpx.Response(200, content=b"index contents")

    with client_for(handler) as c:
        result = get(URL, client=c)
    assert result.body == b"index contents"


def test_304_returns_stored_validators_not_response_headers():
    # A 304 has no validators of its own; the server may echo whatever it
    # likes (or nothing) in its own etag/last-modified headers on a 304.
    # The result must carry the validators we already held and sent as
    # If-None-Match / If-Modified-Since, not whatever came back on the wire.
    def handler(request):
        return httpx.Response(
            304, headers={"etag": '"server-etag-should-not-be-used"',
                          "last-modified": "Thu, 01 Jan 1970 00:00:00 GMT"})

    with client_for(handler) as c:
        result = get(URL, etag='"stored-etag"',
                     last_modified="Wed, 02 Sep 2026 09:14:00 GMT", client=c)
    assert result.status == 304
    assert result.etag == '"stored-etag"'
    assert result.last_modified == "Wed, 02 Sep 2026 09:14:00 GMT"


def test_server_error_raises():
    def handler(request):
        return httpx.Response(503)

    with client_for(handler) as c:
        with pytest.raises(SourceFetchError, match="503"):
            get(URL, client=c)


# --- Allowlist self-review: adversarial URL/redirect shapes -----------------
#
# These lock in the results of a deliberate attempt to defeat check_url with
# a redirect chain, a scheme change, userinfo-in-URL, and a protocol-relative
# location. None of them got past the allowlist as written; these tests keep
# it that way.

def test_userinfo_prefix_does_not_bypass_allowlist():
    # https://odf.olympictech.org@evil.example/... -- urlsplit().hostname
    # correctly resolves to evil.example (the real connection target), not
    # the string before the '@'. Refused.
    with pytest.raises(SourceFetchError, match="host"):
        check_url("https://odf.olympictech.org@evil.example/x.pdf")


def test_userinfo_suffix_naming_evil_host_is_accepted_for_the_real_host():
    # https://evil.example@odf.olympictech.org/... -- 'evil.example' here is
    # just userinfo (e.g. a bogus username) sent to the real allowed host;
    # the connection target is genuinely odf.olympictech.org. Not a bypass,
    # so check_url must accept it rather than fail closed on a red herring.
    check_url("https://evil.example@odf.olympictech.org/x.pdf")


def test_uppercase_host_is_still_recognised():
    # Host matching must be case-insensitive so a mixed-case legitimate URL
    # isn't rejected -- and, symmetrically, so an attacker can't use case
    # variation to slip past a case-sensitive check in the other direction.
    check_url("https://ODF.OLYMPICTECH.ORG/x.pdf")


def test_uppercase_scheme_is_still_recognised():
    check_url("HTTPS://odf.olympictech.org/x.pdf")


def test_protocol_relative_redirect_off_host_is_refused():
    def handler(request):
        return httpx.Response(
            302, headers={"location": "//evil.example/x.pdf"})

    with client_for(handler) as c:
        with pytest.raises(SourceFetchError, match="host"):
            get("https://odf.olympictech.org/old.pdf", client=c)


def test_redirect_to_http_scheme_is_refused():
    def handler(request):
        return httpx.Response(
            302, headers={"location": "http://odf.olympictech.org/x.pdf"})

    with client_for(handler) as c:
        with pytest.raises(SourceFetchError, match="HTTPS"):
            get("https://odf.olympictech.org/old.pdf", client=c)


def test_subdomain_suffix_trick_is_refused():
    # odf.olympictech.org.evil.example is a distinct host string; the real
    # allowed host is only ever a strict, exact hostname match.
    with pytest.raises(SourceFetchError, match="host"):
        check_url("https://odf.olympictech.org.evil.example/x.pdf")


def test_every_request_carries_the_browser_shaped_user_agent():
    """The IOC site is behind Akamai bot mitigation that resets any request
    whose User-Agent is not browser-shaped. Sending none at all -- httpx's
    default -- made the entire sync feature non-functional on first release:
    every check died with a reset or a read timeout.

    Measured against the live site (2026-09-06): httpx's own default and a
    plain 'ODF-Validator/1.0' were both reset; the Mozilla-prefixed token
    returned 200 in 0.5s. So this asserts BOTH halves -- the prefix the filter
    requires, and this app's own name, which is what keeps the request
    truthful about who is making it.
    """
    seen = {}

    def handler(request):
        seen.update(request.headers)
        return httpx.Response(200, content=b"%PDF-1.7",
                              headers={"content-type": "application/pdf"})

    with client_for(handler) as c:
        get(URL, expect="dd", client=c)

    ua = seen.get("user-agent", "")
    assert ua.startswith("Mozilla/5.0"), (
        f"the bot filter rejects any User-Agent without a browser-shaped "
        f"prefix; got {ua!r}")
    assert "ODF-Validator" in ua, (
        f"the User-Agent must still name this application rather than "
        f"impersonating a browser outright; got {ua!r}")


def test_the_user_agent_survives_a_redirect_hop():
    """A redirect re-issues the request; the header has to go with it, or the
    second hop is the one that gets reset."""
    seen = []

    def handler(request):
        seen.append(request.headers.get("user-agent"))
        if request.url.path.endswith("old.pdf"):
            return httpx.Response(
                302, headers={"location": "https://odf.olympictech.org/new.pdf"})
        return httpx.Response(200, content=b"%PDF-1.7",
                              headers={"content-type": "application/pdf"})

    with client_for(handler) as c:
        get("https://odf.olympictech.org/old.pdf", expect="dd", client=c)

    assert len(seen) == 2
    assert all(ua and ua.startswith("Mozilla/5.0") for ua in seen), seen
