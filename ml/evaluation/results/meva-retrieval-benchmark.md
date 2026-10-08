# Retrieval benchmark on real labels (MEVA activity clips)

**Run 2026-10-06 17:17 UTC**, local profile, camera `meva-ex`: 121 labelled clips of 36 activities joined into a 36-minute stream, 221 recorded windows. Produced by `ml/evaluation/retrieval/meva_benchmark.py`; the labels are the MEVA clip names, nobody annotated anything.

How to read it: a result window is relevant when it overlaps a clip of the queried activity by at least 2 s. Numbers are averaged over the queries (one per activity). *Random* is what k random windows would score. The stream is short staged clips separated by black gaps, which is far easier to separate than a day of one camera, so these numbers are a ceiling for hard footage, not a promise.

Timeline alignment: the stream start was found at an offset scoring 389 (runner-up -11); 17% of tracks began in black frames (noise); ingestion joined 26.2 s late; the same offset follows from the simulator's start time.

## fast mode

| | @1 | @3 | @5 | @10 |
|---|---|---|---|---|
| hit (any relevant window) | 0.139 | 0.306 | 0.361 | 0.556 |
| random hit | 0.027 | 0.079 | 0.128 | 0.239 |
| precision | 0.139 | 0.111 | 0.083 | 0.067 |
| random precision | 0.027 | 0.027 | 0.027 | 0.027 |
| share of the activity's clips reached | 0.088 | 0.212 | 0.249 | 0.336 |

Mean reciprocal rank 0.245; 92% of returned windows lie on some clip rather than black; median 0.24 s per query; 0 of 36 queries carried a degradation note.

| family | queries | hit@1 | hit@5 | hit@10 | precision@5 | MRR |
|---|---|---|---|---|---|---|
| building | 3 | 0.0 | 0.0 | 0.333 | 0.0 | 0.056 |
| object | 5 | 0.2 | 0.2 | 0.2 | 0.04 | 0.2 |
| people | 5 | 0.0 | 0.2 | 0.4 | 0.04 | 0.129 |
| person-vehicle | 10 | 0.0 | 0.4 | 0.7 | 0.08 | 0.178 |
| posture-device | 7 | 0.429 | 0.857 | 1.0 | 0.2 | 0.586 |
| vehicle-motion | 6 | 0.167 | 0.167 | 0.333 | 0.067 | 0.19 |

| activity | clips | first relevant rank | hit@10 | precision@10 |
|---|---|---|---|---|
| vehicle-uturn | 4 | 1 | 1 | 0.2 |
| heavy-carry | 3 | 1 | 1 | 0.2 |
| talk-on-phone | 3 | 1 | 1 | 0.2 |
| text-on-phone | 3 | 1 | 1 | 0.1 |
| riding | 3 | 1 | 1 | 0.1 |
| vehicle-picksup-person | 4 | 2 | 1 | 0.1 |
| purchasing | 3 | 2 | 1 | 0.1 |
| close-trunk | 3 | 3 | 1 | 0.1 |
| stand-up | 5 | 3 | 1 | 0.2 |
| laptop-interaction | 3 | 3 | 1 | 0.1 |
| read-document | 3 | 3 | 1 | 0.1 |
| open-trunk | 4 | 4 | 1 | 0.1 |
| enter-vehicle | 3 | 5 | 1 | 0.1 |
| close-vehicle-door | 3 | 6 | 1 | 0.1 |
| load-vehicle | 3 | 6 | 1 | 0.1 |
| unload-vehicle | 3 | 6 | 1 | 0.1 |
| open-facility-door | 4 | 6 | 1 | 0.1 |
| vehicle-reversing | 4 | 7 | 1 | 0.1 |
| object-transfer | 3 | 7 | 1 | 0.1 |
| sit-down | 5 | 10 | 1 | 0.1 |
| exit-vehicle | 4 | - | 0 | 0.0 |
| open-vehicle-door | 3 | - | 0 | 0.0 |
| vehicle-dropsoff-person | 4 | - | 0 | 0.0 |
| vehicle-starting | 4 | - | 0 | 0.0 |
| vehicle-stopping | 4 | - | 0 | 0.0 |
| vehicle-turning-left | 4 | - | 0 | 0.0 |
| vehicle-turning-right | 4 | - | 0 | 0.0 |
| enter-through-structure | 3 | - | 0 | 0.0 |
| exit-through-structure | 4 | - | 0 | 0.0 |
| people-talking | 4 | - | 0 | 0.0 |
| embrace-interaction | 3 | - | 0 | 0.0 |
| hand-interaction | 3 | - | 0 | 0.0 |
| pick-up-object | 3 | - | 0 | 0.0 |
| set-down-object | 3 | - | 0 | 0.0 |
| abandon-package | 1 | - | 0 | 0.0 |
| theft | 1 | - | 0 | 0.0 |

## reason mode

| | @1 | @3 | @5 | @10 |
|---|---|---|---|---|
| hit (any relevant window) | 0.222 | 0.333 | 0.389 | 0.667 |
| random hit | 0.027 | 0.079 | 0.128 | 0.239 |
| precision | 0.222 | 0.12 | 0.083 | 0.072 |
| random precision | 0.027 | 0.027 | 0.027 | 0.027 |
| share of the activity's clips reached | 0.107 | 0.207 | 0.235 | 0.456 |

Mean reciprocal rank 0.321; 94% of returned windows lie on some clip rather than black; median 16.51 s per query; 0 of 36 queries carried a degradation note.

| family | queries | hit@1 | hit@5 | hit@10 | precision@5 | MRR |
|---|---|---|---|---|---|---|
| building | 3 | 0.0 | 0.0 | 0.333 | 0.0 | 0.037 |
| object | 5 | 0.0 | 0.2 | 0.4 | 0.04 | 0.083 |
| people | 5 | 0.0 | 0.4 | 0.8 | 0.08 | 0.233 |
| person-vehicle | 10 | 0.2 | 0.5 | 0.8 | 0.1 | 0.348 |
| posture-device | 7 | 0.571 | 0.571 | 1.0 | 0.143 | 0.627 |
| vehicle-motion | 6 | 0.333 | 0.333 | 0.333 | 0.067 | 0.333 |

| activity | clips | first relevant rank | hit@10 | precision@10 |
|---|---|---|---|---|
| enter-vehicle | 3 | 1 | 1 | 0.1 |
| vehicle-picksup-person | 4 | 1 | 1 | 0.1 |
| vehicle-turning-right | 4 | 1 | 1 | 0.1 |
| vehicle-uturn | 4 | 1 | 1 | 0.2 |
| stand-up | 5 | 1 | 1 | 0.2 |
| talk-on-phone | 3 | 1 | 1 | 0.1 |
| text-on-phone | 3 | 1 | 1 | 0.1 |
| riding | 3 | 1 | 1 | 0.1 |
| close-trunk | 3 | 2 | 1 | 0.1 |
| purchasing | 3 | 2 | 1 | 0.1 |
| unload-vehicle | 3 | 3 | 1 | 0.1 |
| embrace-interaction | 3 | 3 | 1 | 0.1 |
| close-vehicle-door | 3 | 4 | 1 | 0.1 |
| heavy-carry | 3 | 4 | 1 | 0.1 |
| open-trunk | 4 | 6 | 1 | 0.1 |
| people-talking | 4 | 6 | 1 | 0.1 |
| object-transfer | 3 | 6 | 1 | 0.1 |
| theft | 1 | 6 | 1 | 0.1 |
| read-document | 3 | 6 | 1 | 0.1 |
| load-vehicle | 3 | 8 | 1 | 0.1 |
| laptop-interaction | 3 | 8 | 1 | 0.1 |
| open-facility-door | 4 | 9 | 1 | 0.1 |
| open-vehicle-door | 3 | 10 | 1 | 0.1 |
| sit-down | 5 | 10 | 1 | 0.1 |
| exit-vehicle | 4 | - | 0 | 0.0 |
| vehicle-dropsoff-person | 4 | - | 0 | 0.0 |
| vehicle-reversing | 4 | - | 0 | 0.0 |
| vehicle-starting | 4 | - | 0 | 0.0 |
| vehicle-stopping | 4 | - | 0 | 0.0 |
| vehicle-turning-left | 4 | - | 0 | 0.0 |
| enter-through-structure | 3 | - | 0 | 0.0 |
| exit-through-structure | 4 | - | 0 | 0.0 |
| hand-interaction | 3 | - | 0 | 0.0 |
| pick-up-object | 3 | - | 0 | 0.0 |
| set-down-object | 3 | - | 0 | 0.0 |
| abandon-package | 1 | - | 0 | 0.0 |

