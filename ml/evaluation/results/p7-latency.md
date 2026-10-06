# P7-D4 — Latency of the running stack

**Measured 2026-10-04 08:46 UTC** on the build machine (RTX 3050 Laptop 4 GB, Ryzen 5 5600H, 14 GB RAM), local profile: text tasks on `qwen2.5:3b`, vision tasks on `qwen2.5vl:3b` through Ollama, SigLIP 2 and SAM 2.1-tiny on CPU. One real camera (`cam01`).

Produced by `ml/evaluation/latency/measure.py`. Times are seconds as an operator sees them (HTTP through the real services); percentiles come from the `n` shown, so treat p95 of a small `n` as a rough upper bound, not a distribution.

### Text search, fast mode (end to end)

| | n | p50 | p95 | min | max |
|---|---|---|---|---|---|
| wall | 30 | 0.221 | 0.247 | 0.206 | 0.262 |

### Fast mode, by stage

| | n | p50 | p95 | min | max |
|---|---|---|---|---|---|
| plan | 30 | 0.0 | 0.0 | 0.0 | 0.0 |
| encode | 30 | 0.06 | 0.069 | 0.048 | 0.08 |
| retrieve | 30 | 0.021 | 0.026 | 0.016 | 0.027 |
| fuse | 30 | 0.137 | 0.149 | 0.13 | 0.163 |
| total | 30 | 0.217 | 0.242 | 0.201 | 0.257 |

### Text search, reason mode (end to end)

| | n | p50 | p95 | min | max |
|---|---|---|---|---|---|
| wall | 5 | 15.552 | 18.412 | 14.684 | 18.635 |

### Reason mode, by stage

| | n | p50 | p95 | min | max |
|---|---|---|---|---|---|
| plan | 5 | 2.324 | 2.419 | 2.219 | 2.439 |
| encode | 5 | 0.181 | 0.215 | 0.138 | 0.219 |
| retrieve | 5 | 0.067 | 0.085 | 0.039 | 0.086 |
| fuse | 5 | 0.165 | 0.285 | 0.141 | 0.312 |
| rerank | 5 | 12.826 | 15.52 | 11.85 | 15.699 |
| total | 5 | 15.54 | 18.405 | 14.677 | 18.628 |

### Object masks (SAM 2.1-tiny, CPU)

| | n | p50 | p95 | min | max |
|---|---|---|---|---|---|
| first_request_s | 5 | 1.3 | 1.342 | 0.001 | 1.345 |
| repeat_request_s | 5 | 0.009 | 0.009 | 0.001 | 0.009 |

### Assistant

| | n | p50 | p95 | min | max |
|---|---|---|---|---|---|
| to_lookup_result_and_first_sentence_s | 4 | 0.014 | 0.209 | 0.01 | 0.244 |
| to_first_word_s | 4 | 0.014 | 0.209 | 0.01 | 0.244 |
| whole_turn_s | 4 | 2.133 | 2.654 | 1.945 | 2.732 |

### Pipeline and background work

| | n | p50 | p95 | min | max |
|---|---|---|---|---|---|
| segment end → searchable | 107 | 7.535 | 84.695 | 2.818 | 120.42 |
| reasoning job (all stages) | 6 | 171.97 | 641.994 | 98.049 | 756.596 |
| daily report | 5 | 10.984 | 12.868 | 7.131 | 12.98 |

VLM gate: 12 candidates decided (6 verified, 6 rejected, 0 skipped); model time per candidate p50 15.04 s, p95 115.24 s.

How to read these. Search, mask and assistant timings were taken with the GPU otherwise idle (perception and the VLM gate stopped; the model already loaded). The pipeline lag, reasoning-job and gate figures come from the stack's earlier hours, when perception, the gate, the reasoning worker and Ollama all competed for the 4 GB card — they describe that contended run, and the gate's p95 includes minutes spent with the model running on the CPU. The assistant's first sentence is the lookup's own header line, so "first sentence" arrives with the tool result; the model's own words follow.

Searches that carried a degradation note: fast 0, reason 0.
