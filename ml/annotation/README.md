# Annotation

Two kits, one after the other. Both live in the `tools/annotation_kit` package (`annotation-kit`).

| Step | Kit | Guide | Produces |
|---|---|---|---|
| 1. Mark when each phase of an incident happens | phase annotation (P3-D5) | [phase_guideline.md](phase_guideline.md) | `phase_labels.jsonl` (`phase_labels.v1`) |
| 2. Verify a caption and answers per phase per view | caption and VQA (P3-J6) | [caption_vqa/README.md](caption_vqa/README.md) | `phavr_labels.jsonl` (`phavr_label.v1`) |

`phase_labels.jsonl` is what step 2 reads; its shape is frozen (`phase_export_example.json`). The Label Studio
configs here are generated (`phase/`, `caption_vqa/`): change the phases or the question bank, regenerate, and a
test fails if a committed config is out of date.
