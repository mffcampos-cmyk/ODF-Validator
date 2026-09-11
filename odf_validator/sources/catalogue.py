from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import PurePosixPath, PureWindowsPath
from urllib.parse import urljoin, urlsplit
import re

from lxml import html as lxml_html

# Preference order when a card offers several links: we want the artifact,
# not the human-readable rendering of it.
LINK_PRIORITY = ("pdf", "xls", "zip", "html")

DD_FILENAME = re.compile(r"^ODF_([A-Z0-9]{3})_Data_Dictionary\.pdf$")


def has_directory_component(name: str) -> bool:
    """True if `name` carries a directory component under either Windows' or
    POSIX's path syntax, regardless of which OS this code happens to be
    running on.

    Shared with odf_validator.sources.sync (originally written there for zip
    member names -- see its _stage_archive) and reused here for the exact
    same reason: a bare `pathlib.Path(name).name != name` check only sees the
    HOST os's separator rules, so on POSIX a name like
    '..\\..\\..\\..\\Startup\\evil.pdf' round-trips as its own `.name`
    (backslash is an ordinary filename character there) and slips past that
    check -- even though this app, and the index pages it reads, run on
    Windows too, where that same string IS a real traversal. Checking with
    both PurePosixPath and PureWindowsPath explicitly (never the
    host-dependent bare Path) makes the guard's behaviour identical on every
    platform it runs on.
    """
    return (PurePosixPath(name).name != name
            or PureWindowsPath(name).name != name)


@dataclass(frozen=True)
class CatalogueEntry:
    """One document card from a Games index page.

    `target` is where the document belongs inside a ruleset folder, relative
    to it and always POSIX-style. A trailing slash means "an archive whose
    members are extracted into this directory" rather than a single file.
    """
    reference: str
    title: str
    published: date | None
    kind: str                 # dd | codes | schema | general | unknown
    url: str                  # absolute; "" when kind == "unknown"
    target: str               # ruleset-relative; "" when kind == "unknown"
    discipline: str | None    # set only for kind == "dd"


def parse_catalogue(html: str, base_url: str) -> list[CatalogueEntry]:
    """Parse a Games index page into document entries.

    Pure: takes markup, returns records. The caller does the fetching, which
    is what lets every parser test run against a committed fixture.
    """
    doc = lxml_html.fromstring(html)
    return [_entry(card, base_url) for card in _by_class(doc, "doc-card")]


def _by_class(node, css_class: str, tag: str = "*") -> list:
    """Descendants carrying a class, by XPath.

    lxml's .cssselect() would read better but needs the `cssselect` package,
    which this project does not depend on. The concat/normalize-space idiom is
    the standard way to match one class out of a multi-class attribute without
    also matching 'doc-card-header'.
    """
    return node.xpath(
        f".//{tag}[contains(concat(' ', normalize-space(@class), ' '),"
        f" ' {css_class} ')]")


def _text(card, css_class: str) -> str:
    found = _by_class(card, css_class)
    return found[0].text_content().strip() if found else ""


def _entry(card, base_url: str) -> CatalogueEntry:
    title = _text(card, "title")
    reference = _text(card, "ref")
    if reference.lower().startswith("reference:"):
        reference = reference.split(":", 1)[1].strip()
    published = _parse_date(_text(card, "date"))

    url = _best_link(card, base_url)
    if not url:
        # e.g. the Header Values card, which announces a document that is not
        # published as a file. Reported to the user, never fetched.
        return CatalogueEntry(reference, title, published, "unknown", "", "",
                              None)

    kind, target, discipline = _classify(url, title)
    return CatalogueEntry(reference, title, published, kind, url, target,
                          discipline)


def _best_link(card, base_url: str) -> str:
    links = {}
    containers = _by_class(card, "links")
    for a in (containers[0].xpath(".//a[@href]") if containers else []):
        for cls in a.get("class", "").split():
            links.setdefault(cls, a.get("href"))
    for cls in LINK_PRIORITY:
        if cls in links:
            return urljoin(base_url, links[cls])
    return ""


def _parse_date(text: str) -> date | None:
    """The date cell holds '19 May 2026', or 'see Olympic' for a document
    shared with another Games, or nothing at all."""
    try:
        return datetime.strptime(text, "%d %B %Y").date()
    except ValueError:
        return None


def _classify(url: str, title: str) -> tuple[str, str, str | None]:
    name = PurePosixPath(urlsplit(url).path).name

    dd = DD_FILENAME.match(name)
    if dd:
        code = dd.group(1)
        return "dd", f"Disciplines/{code}/{name}", code

    if name.lower().endswith(".zip"):
        # Two archives are published: the code tables and the schema. Decide
        # on the title, since both are just '*.zip' by filename.
        if "schema" in title.lower():
            return "schema", "xsd/", None
        return "codes", "codes/", None

    if name.lower().endswith(".pdf"):
        if has_directory_component(name):
            # CRITICAL (final whole-branch review): `name` is the URL's last
            # path segment, taken verbatim -- urljoin and PurePosixPath(...)
            # .name both leave a backslash untouched, since neither treats it
            # as a separator. A hostile or compromised index page can publish
            # an href whose last segment is
            # '..\\..\\..\\..\\Startup\\evil.pdf': harmless on POSIX
            # (the app's dev/CI platform), where the whole string becomes one
            # oddly-named file, but a real path escape once `entry.target`
            # reaches fetch_targets'/apply_targets' Windows filesystem calls
            # in production. Refused here, at the point the target is
            # derived, rather than downstream: the entry becomes "unknown"
            # (reported to the user, exactly like a card with no
            # downloadable link at all) instead of a "general" entry armed
            # with a target nothing downstream can safely join. See
            # sync.py's fetch_targets for the second, defence-in-depth
            # confinement check on entry.target itself.
            return "unknown", "", None
        return "general", name, None

    return "unknown", "", None
