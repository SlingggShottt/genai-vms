# Adapter tg-v1

- Base model: `/home/slingggshottt/vms-annotation/hf/Qwen2.5-VL-3B-Instruct` (4-bit NF4: True).
- Method: QLoRA on the language model's linear layers, r=16, alpha=32,
  dropout 0.0, LR 0.0002 (cosine, 5% warm-up), 3 epochs,
  8 samples per optimizer step, seed 7.
- Data: dataset `tg-real`; samples {'clips': 119, 'frames': 1271, 'frames_outside_every_span': 5, 'labels': {'action': 474, 'aftermath': 385, 'baseline': 302, 'escalation': 16, 'precursor': 94}, 'samples': {'test': 32, 'train': 138, 'val': 26}, 'source_videos': 119}.
  Frames sha256 `858b0dbe9dd92de7eaa57eef747c98b351db526a60fb37e90956e893825db96d`.
  Labels sha256 `c2c35dbe13206a0eb75ddda8d6a43caebd351448b7caced038e5aa641253812b`.
- Trained 54 optimizer steps; best validation loss 0.1082
  .

## Limits

Validation loss is a training signal, not a result. Whether this adapter beats the zero-shot model
is `ml/evaluation/reasoning/` on the test split, which this run did not touch. The data comes from
the annotated clips only; behaviour on other cameras, lighting or event types is not known.
