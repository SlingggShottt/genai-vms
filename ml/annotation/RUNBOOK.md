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
uv run annotation-kit phase-batch $WORK/candidates.json --out-dir $WORK/batch --size 60 --overlap 20 \
    --annotator kuldeep --annotator pankaj
```

`phase-batch` picks a varied batch (rare activities first, then round-robin across activities, one
clip per five-minute slot while there are others), leaves out clips too long for the timeline (over
40 s at the one-second grid; `--max-duration 0` for no limit), and splits it: `--overlap` clips go to
**both** annotators (the agreement figure needs them), the rest are dealt out. Same inputs and
`--seed`, same batch. A clip found unusable after it was cut is dropped with `--exclude <candidate id>`
(repeatable) and the batch is rebuilt; only the clips that are new then need cutting.

## 2. Cut the clips

```bash
uv run annotation-kit cut $WORK/batch/all.json --out-dir $WORK/clips \
    --source-prefix s3://mevadata-public-01/=https://mevadata-public-01.s3.amazonaws.com/ \
    --script $WORK/cut_clips.sh
ml/annotation/scripts/cut_parallel.sh $WORK/cut_clips.sh 5     # five at a time, skips what exists
ml/annotation/scripts/check_clips.sh $WORK/clips                # BAD / SHORT clips; silence is good
```

`cut` reads the sources over HTTP, so nothing is downloaded whole. Each view is re-encoded at
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

Checked for real, with Label Studio 1.23.2 in a headless Brave: the labelling form renders; both
videos play from the served folder; a phase bar is drawn by a slow drag (a fast one makes a
one-frame bar, which the converter rejects as a stray click); the bar's end can be dragged; Undo
removes it; Submit, `Export > JSON` and `phase-convert` / `phase-agreement` give the expected
seconds. Not checked: anything on an annotator's own machine (Windows + WSL2, their Python, the
first-run `pip install`), more than one browser, or a person doing it by hand rather than a script.
Drawing on a *scrolled* timeline did not work in the script, which is why batches exclude clips
that do not fit.
