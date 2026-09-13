# ODF Validator Webapp

A local web app that validates Olympic Data Feed (ODF) XML messages against the
official ODF documentation: XSD structure, Common Code values, and
discipline-specific semantic rules. Findings are reported with severity, location
(line + element path), and a reference to the source rule/document, and can be
exported as JSON.

## Requirements

- Python 3.11+
- Install dependencies:

```bash
pip install -r requirements.txt
```

## First launch

This repository ships the validation rules and the SYOG26 XSD schema, but not
the other IOC source documents (Data Dictionaries, Common Codes). Those are
published by the IOC and are downloaded by the application, so the repository
stays small and the documents stay current.

The schema is included rather than downloaded because the published copy does
not compile — see **Note on the SYOG2026 XSD** below.

1. `pip install -r requirements.txt`
2. Start the application. The SYOG26 ruleset loads with its rules and its
   schema; `code_membership` rules cannot fire until the Common Codes workbook
   is imported, and the banner says so.
3. Open **Rulesets**, then **Check and download updates**, then **Apply
   downloaded**.

### What to expect on that first import

Every Data Dictionary is new to this copy of the application, so ingestion
generates draft rules for all 25 of them. Drafts are inert until approved and
the shipped rules work regardless, so the queue at `/drafts` can be reviewed at
your own pace or ignored entirely.

Data Dictionaries are converted with `pdf-inspector`, falling back to
`markitdown` if that fails — for instance where no `pdf-inspector` wheel exists
for your platform. A fallback conversion is reported on the rulesets page,
because the obligation parser is tuned to `pdf-inspector`'s output and rules
derived from a fallback conversion deserve a second look.

### Running the tests before the import

Tests that need a compiled schema or the real code tables are skipped until the
import has happened, so a fresh clone reports roughly 596 passed and 89
skipped. After importing, the full suite runs.

## Run

```bash
uvicorn api.app:app
```

The validator page opens in your browser automatically. To disable that
(e.g. on a headless server) set `ODF_NO_BROWSER=1`; to change the URL set
`ODF_OPEN_URL`. Then open http://127.0.0.1:8000/ manually if needed.

Paste a message, upload one `.xml`, or batch multiple files / a `.zip`. Pick a rule
pack, click Validate, and Export JSON.

## Tests

```bash
pytest -v
```

The unit suite (`tests/unit`) exercises the engine against the real SYOG2026 pack;
`tests/integration` exercises the FastAPI layer (requires the web dependencies).
Before the first import, the tests that need a compiled schema or the real code
tables skip — see **First launch** above.

## How it works

A **ruleset** is a folder (`Rules/<name>/`, e.g. `Rules/SYOG26/`) you drop official source
files into: XSD schemas, Common Codes (Excel/XML), and Data Dictionaries (PDF/Word/Markdown,
one per discipline under `Rules/<name>/Disciplines/<discipline>/`). The app scans `Rules/`
at startup, ingests anything new or changed, and heuristically drafts candidate semantic
rules from Data Dictionaries for review at `/drafts` — nothing a Data Dictionary implies
becomes active until approved. See `docs/adding-a-ruleset.md` and
`docs/adding-a-discipline.md` to extend it.

The engine runs an immutable, game-agnostic **core** first — XML well-formedness, XSD conformance (hard-gated: a pack without a compiling XSD reports an ERROR on every run), and engine-bundled `CORE_*` rules (envelope fields, Common Code membership for CompetitionCode/Discipline, Foundation Principles conventions). Game **pack rules** run after the core and can never override or remove core checks.

The core engine (`odf_validator/`) has no web dependencies and is independently
testable.

## Note on the SYOG2026 XSD

**The schema under `Rules/SYOG26/xsd/` is not byte-identical to the IOC's
published copy.** It carries two deliberate changes, both recorded here so that
anyone comparing the two can see exactly what differs and why.

1. **`RecordBrokenType` → `pictureType`.** The published
   `odf2-structure.xsd` does not compile as downloaded: element `ImageData`
   (line 915, in `officialCommunicationType`) references a type the schema
   never defines. Of the 219 types it does define, `pictureType` is the one
   used by the schema's other `ImageData` element (in `unitActionType`) and is
   the appropriate string-content image payload type.
2. **Header `@Time` typed as `odfTimeType`** (`[0-9]{9}`) in `odf2.xsd`, where
   the published schema leaves it unconstrained. This is stricter than the
   official schema, not a correction to it.

The IOC will publish no further schema for the Sport Youth Olympic Games 2026,
so this copy is final. It is included in the repository rather than downloaded
because what a clone would download is the copy that does not compile: with
change 1 absent, structural validation stays off and every message reports
`CORE_XSD_INACTIVE`.

The other IOC documents — Data Dictionaries, Common Codes — are unmodified and
are still fetched on first launch.

The engine never skips structural validation quietly. A pack whose schema does
not compile is recorded as a pack load error and hard-gated: every message in
that pack fails structural validation with a mandatory ERROR
(`CORE_XSD_INACTIVE`).

