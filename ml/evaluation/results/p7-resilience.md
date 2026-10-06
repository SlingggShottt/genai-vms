# P7-D5 — Restarting workers mid-stream

**Run 2026-10-04 09:22 UTC**, 420 s, one `docker restart` every 70 s of: indexer, events, correlation. 42 segments were analysed and indexed during the run.

Consumer lag left when the checks ran: perception 0, indexer 0, events 0, correlation 0.

| Invariant | Result |
|---|---|
| I1 no gap in any camera's segment sequence | pass  |
| I2 every segment row has its twin in storage | pass (0 missing) |
| I3 frame points in Qdrant = frames in the twins | pass (839 / 839) |
| I3 track points in Qdrant = tracks in the twins | pass (1403 / 1403) |
| I4 no event in two live correlation groups | pass (0) |

Restarts: vms-indexer (0.3 s), vms-events (0.4 s), vms-correlation (0.4 s), vms-indexer (0.3 s), vms-events (0.3 s)

**All invariants held.**
