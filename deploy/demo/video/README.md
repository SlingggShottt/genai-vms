# Demo video

Records a scripted walkthrough of the real UI (headless Brave, DevTools screencast) scene by scene,
then joins the scenes into one 1080p MP4 with captions drawn on screen. Nothing is mocked: it clicks
through the running stack, so it needs the stack up and fresh footage.

```bash
make up PROFILE=infra,core && deploy/demo/start.sh      # stack
make demo-refresh                                       # ~45 min: fresh footage, events, alerts (footage expires after 24 h)
docker start vms-camera-sim                             # live tiles (swap config/camera_sim.yaml for the MEVA + cam01 manifest first)
cd deploy/demo/video && npm i                           # once (playwright-core)
../../../.venv/bin/python export_slides.py              # study-guide figures -> slides/ (intro and outro)
node record.mjs --list                                  # scenes
node record.mjs                                         # all scenes (05-analyze waits for a real 2-4 min analysis, shown sped up)
node record.mjs 03-search 07-assistant                  # re-record only some
../../../.venv/bin/python assemble.py 00 01 02 03 04 05 06 07 08 09 10 11 13
```

Output: `out/final/GenAI-VMS-demo.mp4`, `.srt` (captions) and `narration.md` (the captions with timestamps,
to read aloud for a voice-over). Each scene is its own recording (`out/<scene>/`), so one that goes wrong
is re-recorded alone. Scenes marked `llm: true` clear the gateway's response cache first so model steps show
their real latency; waits on a model are shown sped up with a badge.

Notes
- `config/topology.yaml` (gitignored) is how the correlation container learns the camera links; links drawn
  in Settings only reach the host API. Events judged after the replay finish arrive too late to be grouped
  across cameras (each group closes before the next event arrives), so the video shows no linked groups.
- Scene `12-observability` (Grafana) is optional and off by default: most scrape targets read 0 on this setup.
- Frames are large (about 2.7 GB for the full set); delete `out/*/frames` after assembling.
