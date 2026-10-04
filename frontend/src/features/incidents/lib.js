export const PHASE_ORDER = ['baseline', 'precursor', 'escalation', 'action', 'aftermath'];

export const PHASE_LABEL = {
  baseline: 'Baseline',
  precursor: 'Precursor',
  escalation: 'Escalation',
  action: 'Action',
  aftermath: 'Aftermath',
};

export const STATUS_LABEL = {
  generating: 'Writing report',
  generated: 'Generated',
  failed: 'Failed',
  reviewed: 'Reviewed',
  closed: 'Closed',
};

/** Share of the window each phase takes, for the timeline band. Zero-length spans keep a sliver
 * so a very short phase is still visible. */
export function phaseShares(timeline) {
  if (!timeline?.length) return [];
  const spans = timeline.map((p) => ({
    ...p,
    ms: Math.max(0, new Date(p.end).getTime() - new Date(p.start).getTime()),
  }));
  const total = spans.reduce((sum, s) => sum + s.ms, 0) || 1;
  return spans.map((s) => ({ ...s, share: Math.max(s.ms / total, 0.04) }));
}

/** Look an evidence id up in the bundle: what it is, in words. */
export function evidenceIndex(evidence) {
  const index = new Map();
  if (!evidence) return index;
  for (const e of evidence.events ?? []) {
    index.set(e.id, {
      kind: 'Detected event',
      text: e.caption || `${e.event_type} on ${e.camera_id}`,
    });
  }
  for (const phase of evidence.phases ?? []) {
    for (const view of phase.views) {
      index.set(view.caption.id, {
        kind: `Description · ${phase.phase} · ${view.camera_id}`,
        text: view.caption.text,
      });
      for (const qa of view.vqa) {
        index.set(qa.id, { kind: `Question · ${phase.phase}`, text: `${qa.q} ${qa.a}` });
      }
      for (const fr of view.frames) {
        index.set(fr.id, {
          kind: `Frame · ${phase.phase} · ${view.camera_id}`,
          text: fr.ts,
          url: fr.url,
        });
      }
    }
  }
  return index;
}

export function provenanceNote(provenance) {
  const bits = [];
  if (provenance?.synthesis_model) bits.push(`Report by ${provenance.synthesis_model}`);
  if (provenance?.tg) {
    bits.push(
      provenance.fallback_used
        ? 'phases from detector timing (the model could not place them)'
        : `phases by ${provenance.tg}`,
    );
  }
  if (provenance?.profile) bits.push(`${provenance.profile} profile`);
  return bits.join(' · ');
}
