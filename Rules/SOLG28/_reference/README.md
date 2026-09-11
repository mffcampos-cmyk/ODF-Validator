# SOLG28 (LA2028) ruleset

Scaffold only — no official LA2028 source documents have been added yet.
This ruleset will show up on the app's `/rulesets` page with 0 disciplines
and 0 rules until real files are dropped in below. That's expected: the
engine hard-gates structural validation when no XSD compiles
(`CORE_XSD_INACTIVE`) rather than silently skipping it — see the
project-root `README.md`, "Note on the bundled SYOG2026 XSD".

See `docs/adding-a-ruleset.md` and `docs/adding-a-discipline.md` at the
project root for the full mechanics. Short version, in order:

1. **XSD schema(s).** Drop the LA2028 `.xsd` file(s) anywhere under this
   folder (conventionally `Rules/SOLG28/xsd/`, but no fixed layout is
   required — the loader types files by extension, not location). If the
   entry-point filename isn't `odf2.xsd`, set it in `pack.yaml`:

   ```yaml
   root_xsd: <entry-point-filename>.xsd
   ```

2. **Common Codes.** Drop the LA2028 Common Codes file (`.xlsx`, or `.xml`
   with `<Codeset>` elements) anywhere under this folder (conventionally
   `Rules/SOLG28/codes/`).

3. **Data Dictionaries, one per discipline.** Create
   `Rules/SOLG28/Disciplines/<CODE>/` (e.g. `Disciplines/ARC/`) per LA2028
   sport and drop that discipline's Data Dictionary in (`.pdf`, `.docx`,
   or `.md`). Cross-discipline documents (a GEN doc, Foundation
   Principles) go directly under `Rules/SOLG28/`, not under `Disciplines/`.

4. **Restart the app.** Ingestion runs once at startup: XSDs and Common
   Codes load immediately; each Data Dictionary is heuristically scanned
   for mechanically-detectable rule patterns and lands as a **draft** at
   `/drafts` — nothing becomes active validation until you approve it
   there.

5. **Hand-author rules as needed.** Approved drafts aren't the only path:
   add `Rules/SOLG28/Disciplines/<CODE>/rules/<name>.yaml` (or
   `Rules/SOLG28/rules/<name>.yaml` for cross-discipline rules) directly,
   with `status: active`, using one of the primitives listed in
   `docs/adding-a-discipline.md`. Add a good + a bad corpus sample under
   `tests/corpus/<CODE>/` and assertions in
   `tests/unit/test_<code>_rules.py` for anything hand-authored.

Rule ids starting with `CORE_` are reserved for the engine; a pack rule
using that prefix is dropped with a load error.

`rules/` and `.drafts/` subfolders anywhere under this tree are
app-managed once they exist — don't hand-edit files in `.drafts/` except
to reject a bad draft outright by deleting its entry.

## Fetching source documents automatically

Once the IOC publishes an LA2028 index page, add its URL to `pack.yaml`:

```yaml
source:
  index_url: https://odf.olympictech.org/<games-path>/<page>.html
  check_on_start: true
```

That is the entire change. On the next start the app reads the page, adopts
whatever files are already sitting in this folder, and reports anything newer.
Without `index_url` the sync makes no network requests at all, which is why
this block is absent today.
