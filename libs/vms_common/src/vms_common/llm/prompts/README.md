# Prompt files

One directory per gateway task (the names in `config/models.yaml`), one file per version:

```text
prompts/event_verify/1.0.md      # arrives with P3-D4
prompts/query_decompose/1.0.md
```

- Jinja2, rendered by `vms_common.llm.render_prompt("event_verify", "1.0", **variables)`.
  A variable the template needs but the caller did not pass is an error.
- Every prompt declares its role, its inputs (retrieved or user text inside `<data>` tags),
  the output schema, and what to answer when the evidence is insufficient
  (style_guide.md §A.6).
- **Never edit a released version.** Changing the wording means a new file (`1.1.md`) — the
  version is recorded in provenance and in evaluation results, so old numbers must stay
  reproducible.
