# annotation_kit

The caption/VQA annotation kit (P3-J6): Label Studio configs generated from `config/vqa_bank.yaml`, the
pre-annotation step (prompt, reading the model's reply, Label Studio predictions), and the converter from a
Label Studio export to `phavr_labels.jsonl` with the pseudo-label edit rate. How to use it, start to finish:
`ml/annotation/caption_vqa/README.md`.

```bash
uv run annotation-kit label-config --out ml/annotation/caption_vqa
uv run annotation-kit tasks phase_labels.jsonl --out tasks.json [--url-prefix FROM=TO]
uv run annotation-kit convert export.json --out phavr_labels.jsonl [--report-json edit_rate.json]
```

| Module | Does |
|---|---|
| `schema.py` | the three data formats: the phase export (in), the Label Studio task, `phavr_label.v1` (out) |
| `tasks.py` | phase-labelled clips -> one task per phase per view |
| `labelconfig.py` | the Label Studio XML for an event type's questions |
| `prelabel.py` | prompt (`prompts/prelabel_1.0.md`), tolerant reply parser, Label Studio predictions; the model is a plain callable |
| `convert.py`, `report.py` | export -> labels; how far people moved the drafts |

The model call itself runs in `ml/annotation/caption_vqa/prelabel_kaggle.ipynb` (it needs a GPU); everything
else, including the notebook's pipeline with a placeholder model, is covered by `tests/unit`.
