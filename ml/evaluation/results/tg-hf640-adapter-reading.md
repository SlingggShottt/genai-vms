32 of 32 samples got a usable answer from the model (100%); 0 calls failed outright.

On those 32 answers alone: model mIoU **0.354**, rules on the same clips **0.537**; the model was better on 10, worse on 22, equal on 0.

Stages the model ever said: {'action': 111, 'aftermath': 20, 'baseline': 70, 'escalation': 1, 'precursor': 5}. True stages on the same clips: {'action': 90, 'aftermath': 58, 'baseline': 38, 'escalation': 2, 'precursor': 19}.

| frames shown | no usable answer |
|---|---|
| 5 | 0/6 |
| 6 | 0/10 |
| 7 | 0/11 |
| 8 | 0/5 |

| labels made by | answered clips | model | rules |
|---|---|---|---|
| dataset span | 1 | 0.62 | 0.342 |
| human | 6 | 0.196 | 0.564 |
| model draft (looked at the clip) | 17 | 0.3 | 0.612 |
| model draft (rule only) | 8 | 0.556 | 0.381 |

| exact source | answered clips | model | rules |
|---|---|---|---|
| dataset-span:ucf-crime | 1 | 0.62 | 0.342 |
| draft:frames | 1 | 0.184 | 0.601 |
| draft:padding-rule | 8 | 0.556 | 0.381 |
| draft:zoomed-frames | 16 | 0.307 | 0.612 |
| human:accepted-draft | 4 | 0.233 | 0.559 |
| human:from-scratch | 2 | 0.124 | 0.573 |
