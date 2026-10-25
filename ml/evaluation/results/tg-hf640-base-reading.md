23 of 32 samples got a usable answer from the model (72%); 0 calls failed outright.

On those 23 answers alone: model mIoU **0.211**, rules on the same clips **0.577**; the model was better on 0, worse on 23, equal on 0.

Stages the model ever said: {'action': 68, 'aftermath': 8, 'baseline': 46, 'escalation': 4, 'precursor': 23}. True stages on the same clips: {'action': 72, 'aftermath': 39, 'baseline': 26, 'escalation': 2, 'precursor': 10}.

| frames shown | no usable answer |
|---|---|
| 5 | 0/6 |
| 6 | 7/10 |
| 7 | 0/11 |
| 8 | 2/5 |

| labels made by | answered clips | model | rules |
|---|---|---|---|
| dataset span | 1 | 0.286 | 0.342 |
| human | 5 | 0.171 | 0.564 |
| model draft (looked at the clip) | 10 | 0.169 | 0.736 |
| model draft (rule only) | 7 | 0.288 | 0.392 |

| exact source | answered clips | model | rules |
|---|---|---|---|
| dataset-span:ucf-crime | 1 | 0.286 | 0.342 |
| draft:padding-rule | 7 | 0.288 | 0.392 |
| draft:zoomed-frames | 10 | 0.169 | 0.736 |
| human:accepted-draft | 3 | 0.174 | 0.558 |
| human:from-scratch | 2 | 0.167 | 0.573 |
