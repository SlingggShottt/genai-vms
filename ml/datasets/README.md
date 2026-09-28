# Datasets

Scripts in `download/` fetch the four datasets used across the project
(context.md §4, D-09, techstack.md §6). All access info below was verified
by fetching each dataset's own page on **27 Sep 2026** — re-check if a
script fails, since academic dataset hosting moves.

| Dataset | Role in project | Access | Approx. size | Licence / usage |
|---|---|---|---|---|
| **WILDTRACK** | Overlap-edge correlation demo, live multi-camera simulation (7 synchronized HD cameras) | Direct download, no registration | ~7 GB (annotated frames + calibration); full per-camera video is larger | Not explicitly stated on the dataset page at fetch time — treat as **research/non-commercial**, cite the WILDTRACK CVPR 2018 paper (Chavdarova et al.), and re-check https://www.epfl.ch/labs/cvlab/data/data-wildtrack/ before any other use |
| **MEVA** | Multi-camera correlation, multi-view phase reasoning, activity-style search queries | AWS S3 public bucket (`mevadata-public-01`), no-cost, no registration | Full dataset ~470–516 GB — **scope a subset, see below** | Sponsored by the AWS Public Dataset Program / NIST ActEV; check https://mevadata.org for the exact current terms before use beyond research |
| **UCF-Crime** | Phase annotation for TG/PhaVR fine-tuning, incident search queries (13 anomaly classes, backlog scopes to 8) | Direct download, no registration | Tens of GB (full archive; CRCV doesn't offer a per-class download) | Research use only per CRCV's Real-world Anomaly Detection project (https://www.crcv.ucf.edu/projects/real-world/) |
| **ShanghaiTech Campus** | Rule/event precision-recall (running, loitering-like, bikes) | OneDrive link (Google Drive link on the source page is currently broken) | Dataset paper reports ~330 training + 107 testing videos, ~726 frames avg | Not explicitly stated on the dataset page at fetch time — treat as **research/non-commercial**, cite per https://svip-lab.github.io/dataset/campus_dataset.html |

None of these licences permit redistribution of raw footage beyond
research use as verified above — **do not commit any of these files to
git** (`.gitignore` already excludes `ml/**/*.mp4` etc.). Team-member demo
recordings need everyone filmed to have consented (context.md §6).

## Scoping MEVA to <= 60 GB (P1-D6 AC)

The full bucket is too large to use directly. Pick a scoped subset with
`download/meva.sh`:

```bash
bash ml/datasets/download/meva.sh list                    # see available prefixes
bash ml/datasets/download/meva.sh size drops-123-r13       # check one before committing
bash ml/datasets/download/meva.sh sync drops-123-r13 ...   # sync the chosen prefix(es)
```

Pick prefixes that cover **>= 4 synchronized cameras** at the same
site/time window (needed for the correlation demo, D-09) and keep the
running total under 60 GB (`du -sh ml/datasets/raw/meva`). The exact prefix
names weren't verified against a live bucket listing when this was
written — run `list` first rather than assuming a name from this doc.

## Run all four

```bash
bash ml/datasets/download/wildtrack.sh
bash ml/datasets/download/ucf_crime.sh
bash ml/datasets/download/shanghaitech.sh   # falls back to manual steps — OneDrive can't be scripted reliably
bash ml/datasets/download/meva.sh list      # then size/sync a scoped subset, see above
```

Everything lands under `ml/datasets/raw/<name>/`, which is git-ignored.
None of this was actually run in the environment these scripts were
written in (no network egress budget for tens of GB of downloads here) —
each script was written against verified real URLs/bucket names, but the
first real run should be treated as the first real test of them.
