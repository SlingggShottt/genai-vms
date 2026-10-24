# The labels of the first annotation round (2026-10-17 to 2026-10-24)

| File | What it is |
|---|---|
| `label_studio_export_2026-10-24.json` | Label Studio's own export of everything the annotator submitted or skipped, with the model draft each annotation started from (`annotations[].prediction`). The raw record. |
| `phase_labels_combined.jsonl` | One `phase_labels.v1` line for each of the 119 clips, made by `annotation-kit combine-labels`. The label's `annotator` says where it came from. |

`annotator` is one of:

| value | clips | meaning |
|---|---|---|
| `human:from-scratch` | 9 | a person marked it with no draft behind it |
| `human:accepted-draft:claude-draft-1` | 18 | a person submitted a model draft exactly as drafted |
| `human:corrected-draft:claude-draft-1` | 2 | a person changed the draft |
| `draft:claude-draft-1:frames` | 23 | nobody opened it: Claude's draft, made from a contact sheet of the clip |
| `draft:claude-draft-2:zoomed-frames` | 35 | the same, for a multi-camera clip, from zoomed crops |
| `draft:claude-draft-2:padding-rule` | 25 | no activity could be found: baseline for the first 10 s, action to 10 s before the end, aftermath after |
| `dataset-span:ucf-crime` | 7 | the dataset's own crime span: baseline, action, aftermath |

**Only the first row is a person's own judgement**, and an accepted draft is not that: it is a draft a person
looked at and did not change (the export cannot show whether they watched). Anything computed from these labels
should be reported by source, as `ml/evaluation/results/tg-zero-shot-real.md` is.

The drafts are in `ml/annotation/drafts/`. The clips are not in the repository (licence: research use only);
`ml/annotation/RUNBOOK.md` says how to fetch and cut them again, and the ids in these files say which ones.
