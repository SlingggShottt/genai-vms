# Real-footage detection run — MEVA bus-station slice

**Run 2026-10-04 12:24–13:05 UTC**, local profile (`qwen2.5vl:3b` through Ollama for the verification gate), RTX 3050 4 GB, 14 GB RAM. This is the first time the rules and the VLM gate saw footage that was not the looping `cam01` demo clip. Everything below is what happened; where a number is a sample or an opinion, it says so.

## What was replayed

| Camera | MEVA source | Scene | What was labelled |
|---|---|---|---|
| `bus-g331` | `drops-123-r13/2018-03-15`, camera G331, 15:10–15:20 | Bus-station waiting room, many seated people with bags | `Theft` at 3:26 and `Abandon_Package` at 8:03 into the replay |
| `bus-g340` | camera G340, 15:10:04–15:20:04 | Car park, people at a car boot | nothing relevant to the rules |
| `bus-g505` | camera G505, 15:10–15:20 | Empty entrance canopy | nothing |

Each camera is two 5-minute clips joined (10 min), cut to start together, re-encoded to 1280×720, 15 fps, H.264 baseline, no B-frames, one keyframe per second (the simulator needs this; see `tools/camera_sim/README.md`). The camera simulator played all three in real time through MediaMTX → ingestion → perception → indexer. Ingestion joined about 26 s after the stream started, so each camera has 57 segments (about 9.5 min) and the first ~26 s were never recorded. Perception kept up in real time with three cameras (no consumer lag).

Zones were drawn by hand on one frame per camera (they are not MEVA data): `waiting-area` (generic), `entrance-door` (entrance) and `staff-doorway` (restricted) on G331; `car-park-path` (generic) and `lawn` (restricted) on G340; `entrance-canopy` (entrance) and `forecourt` (generic) on G505. Rules ran with the defaults in `config/rules.yaml`.

Perception found, over the 10 minutes: G331 127 person, 13 backpack, 5 suitcase and 2 handbag tracks; G340 41 car, 30 person, 10 truck, 1 bus and 1 handbag tracks; G505 21 car tracks and no person. Track counts are not head counts: seated people that are occluded come back as new tracks.

## What the rules produced

The events service raised 49 candidates; the VLM gate judged all 49 (0 skipped).

| Camera | Rule | Candidates | Verified | Rejected |
|---|---|---|---|---|
| G331 | loitering | 30 | 30 | 0 |
| G331 | intrusion.restricted (`staff-doorway`) | 9 | 0 | 9 |
| G331 | abandoned_object | 4 | 2 | 2 |
| G331 | crowding | 2 | 2 | 0 |
| G340 | intrusion.restricted (`lawn`) | 3 | 2 | 1 |
| G340 | loitering | 1 | 1 | 0 |
| G505 | (none) | 0 | – | – |
| **Total** | | **49** | **37** | **12** |

`running` and the after-hours rule raised nothing: I saw nobody run in these 10 minutes (I did not watch every second) and no zone had a schedule, so neither rule was really exercised.

Gate time per candidate: median 12 s (verified) and 11 s (rejected); mean 19 s and 17 s; slowest 55 s. The 49 candidates took about 29 minutes of wall-clock (12:36–13:05) because of the memory problem described under "Things that went wrong".

## Does it find the labelled events?

- **Abandon_Package: found (1 of 1).** The MEVA label puts the bag down at 8:03–8:07. At 8:01 the spot is empty and at 8:10 a black bag lies on the floor at the right-hand bench (I checked both frames). The `abandoned_object` rule raised a candidate on that bag at 9:05, 62 s after the drop, which is what its settings imply (30 s still, then 20 s unattended, plus sampling). The gate verified it. Its caption, however, says "A person is sitting on a bench with a bag or suitcase next to them", which argues against abandonment: the yes is right, the stated reason is not.
- **Theft: not found (0 of 1).** No rule targets theft, so nothing could fire. This is a gap in the rule set, not a tuning problem.
- **Precision of `abandoned_object` (sample of 4, my judgement):** the other three candidates are one bag (track `t56`) on the floor beside a group of seated people, with no MEVA label. I think it was attended, but the labels do not say. The rule alone: 1 of 4 is the labelled drop. The gate rejected two of the three `t56` candidates (consistent with my reading) and verified the third ("a bag … has been left on its own, with no person near it") — the same bag, about a minute after a rejection. So 1 of the 2 verified events is the labelled one. These samples are tiny; do not quote percentages from them.

## What the other rules and the gate do

- **loitering: 31 of 31 verified, and no use to anyone.** Captions read "sitting on a bench in a waiting area, reading a book / looking at their phone", for 60–270 s. Both the rule and the model are right: people in a waiting room stay put. The result is 30 alerts about waiting passengers. The default needs a per-zone override (`rules.yaml` → `overrides`, for example `enabled: false` or a long `dwell_s` for `waiting-area`). I did not apply one.
- **intrusion.restricted: not scorable.** The zones are mine and MEVA has no zone ground truth. In the two frames I opened, a person really was standing inside the polygon, so the rule's geometry was right. The gate rejected 10 of 12; four of the doorway rejections carry captions that say "A person is standing in the restricted area", so the verdict and the caption disagree. It saw no sign that the door was off-limits, which fits: it is not told the zone is restricted beyond the name. The rule also counts vehicles, so a parked silver SUV in the `lawn` polygon raised candidates; the same SUV was rejected at 0:29 and verified at 8:40.
- **crowding: 2 of 2 verified**, both in the waiting room. The frames show many seated and standing people; I did not count them against `max_persons: 8`.
- **Gate consistency.** In this sample the verdict contradicted its own caption in at least five of 49 cases, and the same object got opposite verdicts at different times. The gate cut the candidates that were clearly not events (a person sitting next to their bag) but it is not a reliable second opinion on "restricted" or "abandoned" with the 3B model at 8 k context. Treat 12 s per candidate and the verdict as a filter, not a ruling.

## Things that went wrong, and what they cost

- **Memory.** With perception stopped, the gate's Ollama runner used 6.3 GB of RAM (about half of `qwen2.5vl:3b` runs on the CPU), the retrieval service held 2.7 GB, and swap filled (4 GB). Image decoding slowed to ~20 s per batch and one request timed out after 2 min. Stopping retrieval helped. Ollama then exited at some point after 12:50 UTC; I did not establish why (no kernel log access). The gate holds candidates with back-off and would have published them `skipped` after 10 min; I restarted Ollama in time and nothing was skipped.
- **The old backlog.** About 8,500 earlier candidates were still undecided. The gate judges high severity first, then oldest, so they would have queued ahead of this run. The gate's maximum age was set to 40 minutes for the run (`VMS_EVENTS_VERIFY_MAX_AGE_SECONDS=2400`, a compose override kept outside the repo) so only the new candidates were judged.
- **Alerts.** Each verified event created an alert: 37 new open alerts (4 high, 33 medium), all on cameras `bus-g331` and `bus-g340`.
- **Cross-camera correlation was not exercised.** There is no `config/topology.yaml`, so every event is its own group.

## How to repeat it

1. Download from the public bucket (anonymous HTTPS, no `aws` CLI needed): `https://mevadata-public-01.s3.amazonaws.com/drops-123-r13/2018-03-15/15/2018-03-15.15-{10-00.15-15-00,15-00.15-20-00}.bus.G331.r13.avi` (and the matching G340 `15-10-04.15-15-04` / `15-15-04.15-20-04` and G505 files). About 0.7 GB. The activity labels are under `examples/annotations/2018-03-15/15/`. MEVA video is research-only: keep it under `ml/datasets/raw/` (gitignored).
2. Join and re-encode each camera with the `camera-sim` image's `ffmpeg` (`-ss 4` on G331 and G505, `concat`, `fps=15,scale=1280:-2`, `-profile:v baseline -bf 0 -g 15`).
3. Add the cameras to `config/cameras.yaml`, the zones to `config/zones.yaml`, the three files to `config/camera_sim.yaml` (all gitignored), and register them through the API if you want them in the UI.
4. Start perception first, then the simulator; after the clip ends stop both, then start the events service and Ollama so the gate has the GPU (the 4 GB card cannot hold perception and the VLM).

Labels cover only some activities, background people are real bystanders, and the clips are one 10-minute stretch of one afternoon at one site, so none of this says how the system behaves on other footage.
