# Caption and VQA annotation kit (P3-J6)

People verify, per **phase of a clip in one camera's view**, a caption and a set of questions. A model
drafts them first, so checking is faster than writing. What comes out is `phavr_labels.jsonl`, the
training data for the PhaVR adapter (design section 8.3), and a measure of how much people had to change.

```text
phase_labels.jsonl ──annotation-kit tasks──▶ tasks ──Kaggle notebook (Qwen2.5-VL-7B)──▶ preannotated_tasks.json
   (phase kit, P3-D5)                                                                          │
                                                                              Label Studio: import, verify, export
                                                                                                │
                              phavr_labels.jsonl + edit rate ◀──annotation-kit convert── export.json
```

`config/vqa_bank.yaml` is the one list of questions: the labelling form is generated from it, the model is
asked exactly those questions, and the adapter is scored on them.

## Set up a project (once per event type)

Questions differ by event type, and a Label Studio config is fixed, so there is one config per type:
`intrusion.xml`, `loitering.xml`, `crowding.xml`, `abandoned_object.xml`, `running.xml`, and `default.xml`
for any other type. They are generated; do not edit them by hand.

1. Label Studio > Create project > Labeling Setup > Custom template > paste `<event type>.xml`.
2. After changing `config/vqa_bank.yaml`, regenerate: `uv run annotation-kit label-config --out ml/annotation/caption_vqa`.
   A test fails if the committed files are out of date.

## Get tasks and drafts

```bash
# one task per phase per view (a 4-phase clip seen by 3 cameras is 12 tasks)
uv run annotation-kit tasks phase_labels.jsonl --out tasks.json \
    --url-prefix s3://vms-evidence/=https://media.example/evidence/
```

`--url-prefix` rewrites a stored `s3://` uri into something Label Studio's player can fetch (the model keeps
the original). Then run `prelabel_kaggle.ipynb` on a Kaggle T4 with Internet on; it writes
`preannotated_tasks.json`. Set `FAKE_MODEL = True` first to check the pipeline on any CPU. Import
`preannotated_tasks.json` into the matching project: the drafts appear filled in.

## What an annotator does

For each task the clip plays **only that phase**, in **that camera's view**.

- **Caption.** One or two sentences about what is visible in this view during this phase. Say what people and
  objects do ("a person in a dark jacket walks along the fence and looks toward the gate"), not who they are or
  what they intend ("a thief casing the place"). Do not describe other phases or other cameras. If the draft is
  right, leave it; if it is wrong or vague, rewrite it. Do not accept without watching.
- **Questions.** Answer every one; they are required. Choose **Cannot tell** whenever the answer is not
  visible in this view during this phase: a guess teaches the model to guess.
- **Usable?** Choose **No** if the phase cannot be seen in this view (the person is out of frame, the camera is
  blocked). That task is left out of the training data.

## Export and measure

Label Studio > Export > JSON (the full format, with annotations and predictions), then:

```bash
uv run annotation-kit convert export.json --out phavr_labels.jsonl --report-json edit_rate.json
```

A task becomes a label only if it is usable, has a caption and has a valid answer to every question for its event
type; the rest are skipped and counted by reason. If a task has more than one annotation, the latest one wins.
The report says, per event type:

| Column | Meaning |
|---|---|
| Captions edited | share of drafted labels whose caption changed in words (case, punctuation and spacing do not count) |
| Caption rewrite | how much of the caption changed on average, 0 % = kept, 100 % = nothing in common |
| Answers changed | share of all answers a person changed |
| Untouched | share of labels where neither the caption nor any answer changed |

A rate near 0 % everywhere is as suspicious as one near 100 %: it can mean a very good model, or annotators
accepting without reading. Spot-check a sample before trusting it.

## `phavr_labels.jsonl` (`phavr_label.v1`)

One line per verified (clip, view, phase): `clip_id`, `source_video` (split train/val/test by this, never by
clip), `event_type`, `view`, `phase`, `start_s`, `end_s`, `caption`, `vqa` (`id`, `q`, `a`), `annotator`, and the
model's `pseudo` draft with `edits` (what changed), so a reader can see what a person corrected.

## Input contract

`phase_labels.jsonl` is one `phase_labels.v1` clip per line; see `../phase_export_example.json`. **This shape is
a proposal** from this kit: the phase annotation kit (P3-D5) owns the export and should confirm or extend it
(adding optional fields is fine).
