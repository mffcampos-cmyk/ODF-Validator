# Adding / updating a ruleset

Create `Rules/<name>/` (e.g. `Rules/SYOG26/`) and drop in the official source files —
anywhere in the tree, no required subfolder layout:

- XSD schemas (`.xsd`)
- Common Codes (`.xlsx`, or `.xml` with `<Codeset>` elements)
- Data Dictionaries, one per discipline, under `Rules/<name>/Disciplines/<discipline>/`
  (`.pdf`, `.docx`, or already-converted `.md`); cross-discipline documents (e.g. the GEN
  doc) go directly under `Rules/<name>/`.

Optional `pack.yaml` at the ruleset root: `version:` and `root_xsd:` (filename of the schema entry point; default `odf2.xsd`). For example:

```yaml
version: "2.1"
root_xsd: odf2-structure.xsd
```

Rule ids starting with `CORE_` are reserved for the engine — a pack rule using the prefix is dropped with a load error.

Restart the app to pick up new/changed files (ingestion runs once at startup, not live).
Each file is typed by extension/content, not location. XSDs and Common Codes are ingested
immediately. Data Dictionaries are converted to Markdown and heuristically scanned for
mechanically-detectable rule patterns (`CC@<SET>` code references, "Positive Integer" type
hints); candidates land as **drafts** — review and approve or reject them at `/drafts`
before they affect validation. Unchanged files (tracked by content hash) are never
reprocessed, so approving a draft is permanent until its source file actually changes.

`rules/` and `.drafts/` subfolders anywhere under `Rules/<name>/` are app-managed — don't
hand-edit files there except to reject a bad draft outright by deleting its entry.
