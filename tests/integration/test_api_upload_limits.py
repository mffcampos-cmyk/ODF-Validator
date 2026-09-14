"""Bounds on the request path.

A review found a 540-byte zip expanded to 28.6s of blocking CPU and a
3.8MB response, a corrupt zip raised BadZipFile as an unhandled 500, and two
files with the same name silently collapsed into one result.
"""
import io
import zipfile

from fastapi.testclient import TestClient

import api.app as app_module
from api.app import MAX_UPLOAD_BYTES, app

client = TestClient(app)

XML = (b'<OdfBody CompetitionCode="SYOG2026" DocumentCode="ARC" '
       b'DocumentType="DT_SCHEDULE" Version="1" Date="d" Time="t" '
       b'LogicalDate="d" FeedFlag="P" Source="S"><Competition>'
       b'<Discipline Code="ARC-------------------------------"/>'
       b'</Competition></OdfBody>')


def _pack_name():
    return client.get("/packs").json()[0]["name"]


def test_a_corrupt_zip_is_a_client_error_not_a_crash():
    r = client.post("/validate/batch",
                    data={"pack": _pack_name()},
                    files=[("files", ("bad.zip", b"PK\x03\x04garbage", "application/zip"))])

    assert r.status_code == 400
    assert "zip" in r.text.lower()


def test_duplicate_filenames_both_survive():
    files = [("files", ("DT_RESULT.xml", XML, "text/xml")),
             ("files", ("DT_RESULT.xml", XML, "text/xml"))]

    r = client.post("/validate/batch", data={"pack": _pack_name()}, files=files)

    assert r.status_code == 200
    assert len(r.json()["files"]) == 2, \
        "a same-named second file must not overwrite the first"


def test_the_cap_is_the_agreed_150mb():
    assert MAX_UPLOAD_BYTES == 150 * 1024 * 1024


def test_an_oversized_upload_is_refused(monkeypatch):
    # The constant is read inside the handler, so lowering it here exercises
    # the limit without building a 150MB payload in the test process.
    monkeypatch.setattr(app_module, "MAX_UPLOAD_BYTES", 1024)
    big = b"<a/>" + b" " * 2048

    r = client.post("/validate",
                    data={"pack": _pack_name()},
                    files={"file": ("big.xml", big, "text/xml")})

    assert r.status_code == 413


def test_a_zip_bomb_is_refused_on_its_declared_expanded_size(monkeypatch):
    monkeypatch.setattr(app_module, "MAX_UPLOAD_BYTES", 4096)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        # Compresses to a few hundred bytes; expands well past the lowered cap.
        z.writestr("bomb.xml", b"<a/>" + b"0" * 100_000)
    payload = buf.getvalue()
    assert len(payload) < 4096, "the archive itself must be under the cap"

    r = client.post("/validate/batch",
                    data={"pack": _pack_name()},
                    files=[("files", ("bomb.zip", payload, "application/zip"))])

    assert r.status_code == 413


def test_a_normal_batch_still_works():
    r = client.post("/validate/batch",
                    data={"pack": _pack_name()},
                    files=[("files", ("a.xml", XML, "text/xml"))])

    assert r.status_code == 200
    assert list(r.json()["files"]) == ["a.xml"]


def test_too_many_zip_members_is_refused():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i in range(6):
            z.writestr(f"m{i}.xml", XML)
    payload = buf.getvalue()

    import api.app as app_mod
    old = app_mod.MAX_ZIP_MEMBERS
    app_mod.MAX_ZIP_MEMBERS = 5
    try:
        r = client.post("/validate/batch",
                        data={"pack": _pack_name()},
                        files=[("files", ("many.zip", payload, "application/zip"))])
    finally:
        app_mod.MAX_ZIP_MEMBERS = old

    assert r.status_code == 413
    assert "limit is 5" in r.text


def test_a_password_protected_member_is_a_400_not_a_500():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.setpassword(b"secret")
        z.writestr("m.xml", XML, zipfile.ZIP_DEFLATED)
    # zipfile's own writer doesn't encrypt; simulate encryption by setting
    # the general-purpose bit flag that marks a member as password-protected,
    # which is what makes zipfile.open() raise RuntimeError on read.
    payload = bytearray(buf.getvalue())
    # local file header flag bits are 2 bytes at offset 6; set bit 0 (encrypted)
    payload[6] |= 0x01
    # the same flag field is duplicated in the central directory record
    cd_flag_offset = payload.find(b"PK\x01\x02")
    assert cd_flag_offset != -1
    payload[cd_flag_offset + 8] |= 0x01
    payload = bytes(payload)

    r = client.post("/validate/batch",
                    data={"pack": _pack_name()},
                    files=[("files", ("locked.zip", payload, "application/zip"))])

    assert r.status_code == 400
    assert "zip" in r.text.lower()


def test_a_member_with_understated_file_size_is_a_400_not_a_500():
    # Build a valid zip, then patch the declared (and true) size fields down
    # so the CRC/size zipfile checks on read no longer match the real bytes,
    # forcing BadZipFile ("Bad CRC-32") to surface from z.open()/read()
    # rather than from the ZipFile() constructor.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        z.writestr("m.xml", XML)
    payload = bytearray(buf.getvalue())

    # Local file header: PK\x03\x04, uncompressed size is a 4-byte LE field
    # at offset 22 within the header (after CRC-32 at offset 14).
    lfh = payload.find(b"PK\x03\x04")
    import struct
    orig_size = struct.unpack_from("<I", payload, lfh + 22)[0]
    assert orig_size == len(XML)
    struct.pack_into("<I", payload, lfh + 22, 3)          # understate uncompressed size
    struct.pack_into("<I", payload, lfh + 18, 3)           # and compressed size

    cd = payload.find(b"PK\x01\x02")
    struct.pack_into("<I", payload, cd + 20, 3)             # compressed size
    struct.pack_into("<I", payload, cd + 24, 3)             # uncompressed size
    payload = bytes(payload)

    r = client.post("/validate/batch",
                    data={"pack": _pack_name()},
                    files=[("files", ("understated.zip", payload, "application/zip"))])

    assert r.status_code == 400
    assert "zip" in r.text.lower()


def test_smashed_local_header_magic_is_a_400_not_a_500():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        z.writestr("m.xml", XML)
    payload = bytearray(buf.getvalue())
    lfh = payload.find(b"PK\x03\x04")
    payload[lfh:lfh + 4] = b"XX\x03\x04"   # smash the local-header magic
    payload = bytes(payload)

    r = client.post("/validate/batch",
                    data={"pack": _pack_name()},
                    files=[("files", ("smashed.zip", payload, "application/zip"))])

    assert r.status_code == 400
    assert "zip" in r.text.lower()


def test_an_oversized_member_still_returns_413_not_400(monkeypatch):
    # The 413 for an over-declared member is raised *inside* the same try
    # block that now catches zip-corruption errors. Finding 1's fix must not
    # let that 413 get reinterpreted as a generic "bad archive" 400.
    monkeypatch.setattr(app_module, "MAX_UPLOAD_BYTES", 4096)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("big.xml", b"<a/>" + b"0" * 100_000)
    payload = buf.getvalue()

    r = client.post("/validate/batch",
                    data={"pack": _pack_name()},
                    files=[("files", ("big.zip", payload, "application/zip"))])

    assert r.status_code == 413
    assert r.status_code != 400


def test_a_zip_of_zips_is_refused_rather_than_passing_vacuously():
    # A real IOC delivery (SYOG26_WST_PT1.zip, 2026-09-13) is a zip of three
    # zips. The member filter keeps only names ending .xml, so it matched
    # nothing, `members` stayed empty, and the response was
    # {"totals": {0,0,0}, "files": {}} -- byte-identical to a genuinely clean
    # batch. The operator read "all 0 file(s) conform to SYOG26" and believed
    # 82 messages had been validated. Nothing had been read at all.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ("WST XML.zip", "WST PDF.zip", "WST PSCB.zip"):
            inner = io.BytesIO()
            with zipfile.ZipFile(inner, "w", zipfile.ZIP_DEFLATED) as iz:
                iz.writestr("m.xml", XML)
            z.writestr(name, inner.getvalue())
    payload = buf.getvalue()

    r = client.post("/validate/batch",
                    data={"pack": _pack_name()},
                    files=[("files", ("delivery.zip", payload, "application/zip"))])

    assert r.status_code == 400
    # Name what was found, so the operator knows to unpack rather than
    # wondering why a zip they can plainly see messages inside was rejected.
    assert "3 zip archive" in r.text
    assert "delivery.zip" in r.text


def test_a_zip_holding_only_other_formats_says_so():
    # Same silent pass, different shape: a PDF/PSCB bundle with no XML in it.
    # The message must not say "zip archives" when there are none, or the
    # operator unpacks a zip that has nothing to unpack.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("report.pdf", b"%PDF-1.4 ...")
        z.writestr("scoreboard.pscb", b"...")
    payload = buf.getvalue()

    r = client.post("/validate/batch",
                    data={"pack": _pack_name()},
                    files=[("files", ("bundle.zip", payload, "application/zip"))])

    assert r.status_code == 400
    assert "2 files, none of them .xml messages" in r.text
    assert "zip archive" not in r.text


def test_an_empty_zip_says_it_is_empty():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED):
        pass
    payload = buf.getvalue()

    r = client.post("/validate/batch",
                    data={"pack": _pack_name()},
                    files=[("files", ("empty.zip", payload, "application/zip"))])

    assert r.status_code == 400
    assert "holds no files" in r.text


def test_directory_entries_do_not_count_as_files():
    # zipfile lists folder entries with a trailing slash. Counting them made
    # an archive of empty folders report "holds 2 files", sending the operator
    # looking for messages that were never there.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("WST XML 202608/", b"")
        z.writestr("WST PDF 202608/", b"")
    payload = buf.getvalue()

    r = client.post("/validate/batch",
                    data={"pack": _pack_name()},
                    files=[("files", ("folders.zip", payload, "application/zip"))])

    assert r.status_code == 400
    assert "holds no files" in r.text


def test_loose_files_are_charged_to_the_cumulative_budget(monkeypatch):
    monkeypatch.setattr(app_module, "MAX_UPLOAD_BYTES", 100)
    a = b"<a/>" + b" " * 60
    b = b"<a/>" + b" " * 60
    files = [("files", ("a.xml", a, "text/xml")),
             ("files", ("b.xml", b, "text/xml"))]

    r = client.post("/validate/batch", data={"pack": _pack_name()}, files=files)

    assert r.status_code == 413
