# Running a phase-annotation round

For whoever organises it. The annotators get a package built here and need nothing else
([ANNOTATOR_QUICKSTART.md](ANNOTATOR_QUICKSTART.md) is what they read). Every command is
`uv run annotation-kit <command>`, from the repo root.

```text
meva-candidates ─▶ phase-batch ─▶ cut ─▶ phase-package ─▶ (annotators) ─▶ phase-convert ─▶ phase-agreement
  361 clips         60 clips       .mp4    one folder each    export.json      phase_labels      is it any good?
```

## 1. Prepare (once per round)

```bash
WORK=~/vms-annotation   # anywhere with room: the cut clips are ~15 MB per view
git clone --depth 1 https://gitlab.kitware.com/meva/meva-data-repo.git $WORK/meva-data-repo   # ~7 GB

uv run annotation-kit meva-candidates --repo $WORK/meva-data-repo --out $WORK/candidates.json
# the clone is only needed for this step: keep candidates.json and the clone can be deleted
# (re-cloning takes about 20 minutes)
uv run annotation-kit phase-batch $WORK/candidates.json --out-dir $WORK/batch --size 60 --overlap 20 \
    --annotator kuldeep --annotator pankaj
```

`phase-batch` picks a varied batch (rare activities first, then round-robin across activities, one
clip per five-minute slot while there are others), leaves out clips too long for the timeline (over
40 s at the one-second grid; `--max-duration 0` for no limit), and splits it: `--overlap` clips go to
**both** annotators (the agreement figure needs them), the rest are dealt out. Same inputs and
`--seed`, same batch. A clip found unusable after it was cut is dropped with `--exclude <candidate id>`
(repeatable) and the batch is rebuilt; only the clips that are new then need cutting.

### The crime clips (UCF-Crime)

MEVA is everyday activity: it is the multi-camera part. The crime part comes from UCF-Crime, single
camera, and only its 140 *test* videos have start and end times for the crime.

```bash
uv run annotation-kit ucf-fetch --out $WORK/ucf            # the eight classes: 59 videos, ~1.7 GB, ~5 minutes
uv run annotation-kit ucf-fetch --out $WORK/ucf --dry-run  # what it would fetch, nothing downloaded
uv run annotation-kit ucf-candidates --videos $WORK/ucf/Videos \
    --annotations $WORK/ucf/Temporal_Anomaly_Annotation_for_Testing_Videos.txt \
    --out $WORK/ucf/candidates.json --probe --max-window 40 --uri-prefix ucf://
```

`ucf-fetch` takes the videos from a Hugging Face mirror (`AllenXeon/ucf_crime`): the official host
failed its certificate check. `--classes Shooting Stealing ...` adds others (see the guideline's open
question). `--max-window 40` keeps a long crime to its first 40 s so that the clip fits the timeline.
Put the crime candidates and the MEVA ones in one file and run `phase-batch` over it: its summary
shows how many of each each annotator gets, and the shared set takes both kinds.

## 2. Cut the clips

```bash
uv run annotation-kit cut $WORK/batch/all.json --out-dir $WORK/clips \
    --source-prefix s3://mevadata-public-01/=https://mevadata-public-01.s3.amazonaws.com/ \
    --source-prefix ucf://=$WORK/ucf/Videos/ --min-height 720 \
    --script $WORK/cut_clips.sh
ml/annotation/scripts/cut_parallel.sh $WORK/cut_clips.sh 5     # five at a time, skips what exists
ml/annotation/scripts/check_clips.sh $WORK/clips                # BAD / SHORT clips; silence is good
```

`cut` reads the MEVA sources over HTTP, so nothing is downloaded whole. `--min-height 720` scales a source
shorter than that up to it (a UCF-Crime video is 320x240, and the labelling player shows a video at its own
size); a 1080p MEVA clip is left alone. Each view is re-encoded at
30 fps from the same instant, so the views of a clip stay in sync (checked: both views of a clip
come out with the same frame count). On this machine five in parallel make about 3 views a minute: a 60-clip batch, about
140 views, takes around 45 minutes.
`check_clips.sh` prints `BAD <file>` for a file ffprobe cannot read (a killed ffmpeg leaves one with no
index, and the cut skips files that exist: delete it and cut again) and `SHORT <clip> cam=frames ...`
for a clip whose views differ in length: a source video ended before the window did, so the views no
longer show the same span. This happened to 3 of 219 clips on the first run (a MEVA bus camera whose
recording is shorter than its neighbour's); `--exclude` them from the batch.

## 3. Package, one per annotator

```bash
for who in kuldeep pankaj; do
  uv run annotation-kit phase-package $WORK/batch/$who.json --annotator $who \
      --clips-dir $WORK/clips --out-dir $WORK/packages --link
done
(cd $WORK/packages && zip -0 -r annotation-kuldeep.zip annotation-kuldeep)    # mp4 is already compressed
```

`--link` hard-links the clips instead of copying them (same disk only; use a copy before sending
the folder anywhere else). Send each person their own zip and nobody else's. They unzip it, run
`./start.sh`, and read `README.md` and `QUICKSTART.md` in it.

## 4. Collect and measure

Each annotator sends `export-<name>.json` (after 5 clips, then at the end). The `video_uri`s in what
`phase-convert` writes say `local://clips/...`: when the clips are uploaded for the next step, rewrite
them with `annotation-kit tasks ... --url-prefix local://clips/=<where they are>`.

```bash
uv run annotation-kit phase-convert export-kuldeep.json --out k.jsonl     # what was skipped, and why
uv run annotation-kit phase-convert export-pankaj.json  --out p.jsonl
uv run annotation-kit phase-agreement k.jsonl p.jsonl                    # on the clips both labelled
cat k.jsonl p.jsonl > phase_labels.jsonl   # the shared clips are in twice: choose one, or the guide's
```

Read the first 5 clips of each person before anything else: a misunderstanding costs a day if
it is found late. Agreement targets are in `phase_guideline.md`; they are starting points, not
results.

## If one person annotates everything

With one annotator there is no overlap set, so **no agreement figure** can be measured, and that figure is
what tells you whether the phase definitions are clear. Build one batch for them and package it:

```bash
uv run annotation-kit phase-batch $WORK/combined/candidates.json --out-dir $WORK/batch-me \
    --size 119 --overlap 0 --annotator <name>
uv run annotation-kit phase-package $WORK/batch-me/<name>.json --annotator <name> \
    --clips-dir $WORK/clips --out-dir $WORK/me --link
```

then run `start.sh` in that package (with `LS_BIN`/`PYTHON` set to an installed Label Studio to skip the
`pip install`). To get an honest consistency figure later: re-label about 20 of the clips after a few days
without looking at the first answers (`phase-agreement` on the two files measures how stable one person is),
and have a second person label the same 20 (measures whether the definitions travel). Neither is a
substitute for two people from the start.

## Clips nobody marked: labels from the dataset's own span

For a UCF-Crime clip that was skipped, the dataset's crime span can stand in, as `baseline` (before the span),
`action` (the span) and `aftermath` (after it):

```bash
uv run annotation-kit span-labels $WORK/batch-me/<name>.json \
    --annotations $WORK/ucf/Temporal_Anomaly_Annotation_for_Testing_Videos.txt \
    --skipped-in <the Label Studio export> --out phase_labels_dataset_spans.jsonl
# or name clips: --only <candidate id> (repeatable); --exclude <id> to leave one out
```

These are **weak labels and must stay apart from the hand labels**: they are a separate file, every line has
`annotator: dataset-span:ucf-crime`, they have at most three stages (never `precursor` or `escalation`), and the
spans are rough (two of the first five compared with a person's marks were off: one covered title cards, one
was much shorter than the visible act). Do not count them in the number of hand-labelled clips and do not
score a model against them as if they were human labels. A person's `escalation` (forcing the door) is
inside the dataset's `action` span, so the two do not mean quite the same thing.

## Running Label Studio yourself

To try the annotation screen, or to annotate yourself, from the same inputs:

```bash
ml/annotation/scripts/start_label_studio.sh $WORK          # Label Studio on :8090 serving $WORK/clips
LABEL_STUDIO_TOKEN=... uv run annotation-kit ls-setup --url http://localhost:8090 \
    --annotator kuldeep --tasks-dir $WORK/tasks/kuldeep --media-root $WORK/clips
```

(`phase-tasks ... --clip-prefix local://clips --url-prefix "local://clips/=/data/local-files/?d=clips/"`
makes the tasks; `phase-package` does that for you.) Label Studio 1.22+ switched the old API token
off: use a personal access token (Account & Settings), or give `LABEL_STUDIO_EMAIL` and
`LABEL_STUDIO_PASSWORD` and the loader signs in and makes one.

## What was and was not checked

UCF-Crime, checked 2026-10-17: the mirror is complete (950 anomaly videos, the official count); the
annotation file has the format the reader assumed; every video is H.264, 320x240, 30 fps; six crime clips
were looked at frame by frame and showed activity of the right kind (a vandalism video jumps to another
camera partway through, which is in the original). Not checked: that every labelled span is exactly where
the crime is, or that only 59 labelled videos is enough (see "How many clips").

Checked for real, with Label Studio 1.23.2 in a headless Brave: the labelling form renders; both
videos play from the served folder; a phase bar is drawn by a slow drag (a fast one makes a
one-frame bar, which the converter rejects as a stray click); the bar's end can be dragged; Undo
removes it; Submit, `Export > JSON` and `phase-convert` / `phase-agreement` give the expected
seconds. Not checked: anything on an annotator's own machine (Windows + WSL2, their Python, the
first-run `pip install`), more than one browser, or a person doing it by hand rather than a script.
Drawing on a *scrolled* timeline did not work in the script, which is why batches exclude clips
that do not fit.
