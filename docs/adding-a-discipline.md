# Adding a discipline

Discipline coverage is data, not code. To add a discipline (e.g. Swimming):

1. Semantic rules are declarative YAML using one of the primitives
   (`value_format`, `value_domain`, `code_membership`, `conditional_presence`,
   `set_filter`, `cross_message`, `no_empty_attributes`, `required_attributes`, `forbidden_value`) or `primitive: python` with a registered function.
2. Drop the discipline's Data Dictionary under
   `Rules/<ruleset>/Disciplines/<disc>/` and restart the app; review and approve any
   drafted rules at `/drafts`. Hand-authored rules can also be added directly as
   `Rules/<ruleset>/Disciplines/<disc>/rules/<name>.yaml` with `status: active`.
3. Add corpus samples under `tests/corpus/<disc>/` (a good + a bad message per rule)
   and assertions in a `tests/unit/test_<disc>_rules.py`.

No engine change is required. A rule file is a YAML list; each entry:

```yaml
- id: SWM_SPLIT_POSINT
  applies_to: {doc_types: [DT_RESULT], disciplines: [SWM]}
  primitive: value_domain
  target: ".//Split"
  attribute: Value
  params: {min: 0, integer: true}
  severity: error
  scope: message            # or 'context' for cross-message rules
  source_ref: "SWM DD §x.y"
```
