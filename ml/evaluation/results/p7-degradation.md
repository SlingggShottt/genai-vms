# P7-D5 — With no language model reachable

**Run 2026-10-04 09:30 UTC**, Ollama stopped, everything else up (NFR-REL-04: ingestion, recording, playback and rules continue; GenAI features say they are unavailable instead of hanging).

| Feature | What happened | Time |
|---|---|---|
| Search, fast mode | HTTP 200, 12 results, notes: [] | 0.5 s |
| Search, reason mode | HTTP 200, 12 results (fused order), notes: ['query decomposition skipped (LLMUnavailableError); used keywords', 'reasoning rerank returned nothing usable; showing fused order'] | 0.8 s |
| Assistant question | events: error, error=The assistant's language model is not available right now. Try again in a moment | 0.6 s |
| Events gate (VLM verification) | 953 alert-worthy candidates from the last 6 h have no decision yet; 546 have been tried and are waiting to be retried with back-off (most attempts: 8), the rest are queued behind them; 1098 events were decided in the same period; none were dropped | 0.0 s |
| Daily report | status ready, narrative from the template | 3.0 s |
| Incident analysis job | job failed: the vision model could not describe any stage of this incident | 3.0 s |
