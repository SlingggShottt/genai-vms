import { useState } from 'react';
import { useCameras } from '@/features/cameras/api';
import { SyncedPlayer } from '@/features/playback/components/SyncedPlayer';
import { useIncident } from '../api';
import { PhaseBand } from './PhaseBand';

/** The incident's cameras on one playhead, with its phase band: pressing a phase plays every view
 * for that phase (P5-J5). Used on the event page's Reasoning section; the report page has the
 * same two parts inline because it shares the phase with its per-phase cards.
 */
export function IncidentViews({ incidentId }) {
  const { data: incident, isLoading, isError } = useIncident(incidentId);
  const { data: cameras } = useCameras();
  const [activePhase, setActivePhase] = useState(null);

  if (isLoading) return <p className="text-sm text-text-muted">Loading the views…</p>;
  if (isError || !incident) {
    return (
      <p role="alert" className="text-sm text-sev-critical">
        Could not load the incident’s cameras.
      </p>
    );
  }
  const toggle = (phase) => setActivePhase((prev) => (prev === phase ? null : phase));
  return (
    <div className="flex flex-col gap-2">
      <PhaseBand
        timeline={incident.evidence?.phase_timeline}
        activePhase={activePhase}
        onSelect={toggle}
      />
      <SyncedPlayer
        views={incident.camera_ids.map((code) => ({
          camera: code,
          label: cameras?.items.find((c) => c.code === code)?.name ?? code,
        }))}
        startIso={incident.window_start}
        endIso={incident.window_end}
        timeline={incident.evidence?.phase_timeline}
        activePhase={activePhase}
        onSelectPhase={toggle}
      />
    </div>
  );
}
