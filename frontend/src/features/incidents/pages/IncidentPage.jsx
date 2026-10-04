import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Printer } from 'lucide-react';
import { SeverityBadge } from '@/components/SeverityBadge';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { useCurrentUser } from '@/features/auth/api';
import { AddToCaseDialog } from '@/features/cases/components/AddToCaseDialog';
import { ApiError } from '@/lib/apiClient';
import { eventTypeLabel } from '@/lib/eventTypes';
import { formatClock, formatDateTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { useIncident, useSimilarIncidents, useUpdateIncident } from '../api';
import { EvidenceChips } from '../components/EvidenceChip';
import { PhaseBand } from '../components/PhaseBand';
import { PHASE_LABEL, STATUS_LABEL, evidenceIndex, provenanceNote } from '../lib';

function Section({ title, children }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-base font-semibold text-text">{title}</h2>
      {children}
    </section>
  );
}

function FactorList({ title, items, index, active, onSelect }) {
  if (!items.length) return null;
  return (
    <div className="flex flex-col gap-1">
      <h3 className="text-sm font-medium text-text">{title}</h3>
      <ul className="flex flex-col gap-1 text-sm text-text">
        {items.map((f) => (
          <li key={f.text} className="flex flex-wrap items-baseline gap-2">
            <span>{f.text}</span>
            <EvidenceChips ids={f.evidence} index={index} active={active} onSelect={onSelect} />
          </li>
        ))}
      </ul>
    </div>
  );
}

/** One incident report (§B.7 report view): summary, the phase band, what each phase showed with
 * its evidence, the causal chain, contributing factors, actions and limitations. Every claim carries
 * the evidence it cites; pressing a chip highlights that evidence below.
 */
export function IncidentPage() {
  const { incidentId } = useParams();
  const { data: user } = useCurrentUser();
  const canEdit = user?.role === 'admin' || user?.role === 'operator';
  const { data: incident, isLoading, isError, error } = useIncident(incidentId);
  const update = useUpdateIncident(incidentId);
  const similar = useSimilarIncidents(incident?.status === 'generating' ? null : incidentId);
  const [activeEvidence, setActiveEvidence] = useState(null);
  const [activePhase, setActivePhase] = useState(null);
  const [notes, setNotes] = useState(null);
  const [saving, setSaving] = useState(null);

  const index = useMemo(() => evidenceIndex(incident?.evidence), [incident?.evidence]);

  if (isLoading) return <p className="p-4 text-sm text-text-muted">Loading incident…</p>;
  if (isError || !incident) {
    const missing = error instanceof ApiError && [400, 404].includes(error.status);
    return (
      <div className="flex flex-col items-start gap-2 p-4 text-sm text-text-muted">
        <p>
          {missing
            ? 'This incident was not found.'
            : 'Could not load this incident. Check your connection and try again.'}
        </p>
        <Link to="/incidents" className="text-accent hover:underline">
          All incidents
        </Link>
      </div>
    );
  }

  const report = incident.report;
  const evidence = incident.evidence;
  const select = (id) => setActiveEvidence((prev) => (prev === id ? null : id));
  const frameFor = (id) => {
    for (const p of evidence?.phases ?? [])
      for (const v of p.views) for (const f of v.frames) if (f.id === id) return f;
    return null;
  };

  return (
    <div className="flex h-full flex-col gap-5 overflow-auto p-4 print:overflow-visible">
      <Link to="/incidents" className="text-sm text-accent hover:underline print:hidden">
        All incidents
      </Link>

      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold text-text">{incident.title}</h1>
          <SeverityBadge severity={incident.severity} />
          <span className="text-sm text-text-muted">{STATUS_LABEL[incident.status]}</span>
          <div className="ml-auto flex gap-2 print:hidden">
            {canEdit && (
              <Button
                size="sm"
                variant="outline"
                onClick={() =>
                  setSaving({
                    kind: 'incident',
                    label: incident.title,
                    ref: incident.id,
                    camera_id: incident.camera_ids[0],
                    ts_start: incident.window_start,
                    ts_end: incident.window_end,
                  })
                }
              >
                Save to case
              </Button>
            )}
            <Button size="sm" variant="outline" onClick={() => window.print()}>
              <Printer size={14} aria-hidden="true" />
              Print or save as PDF
            </Button>
          </div>
        </div>
        <p className="text-sm tabular-nums text-text-muted">
          {eventTypeLabel(incident.event_type)} · {incident.camera_ids.join(', ')} ·{' '}
          {formatDateTime(new Date(incident.window_start))} to{' '}
          {formatClock(new Date(incident.window_end))}
          {report && ` · confidence ${Math.round(report.confidence * 100)}%`}
        </p>
      </header>

      {incident.status === 'generating' && (
        <p role="status" className="rounded-panel border border-rule p-3 text-sm text-text-muted">
          The report is being written. This page updates by itself.
        </p>
      )}
      {incident.status === 'failed' && (
        <p
          role="alert"
          className="rounded-panel border border-sev-critical p-3 text-sm text-sev-critical"
        >
          The report could not be written. Analyse the event again from its page.
        </p>
      )}

      {report && (
        <>
          <p className="max-w-3xl text-base text-text">{report.summary}</p>

          <Section title="Phases">
            <PhaseBand
              timeline={evidence?.phase_timeline}
              activePhase={activePhase}
              onSelect={(p) => setActivePhase((prev) => (prev === p ? null : p))}
            />
            <div className="grid gap-3 lg:grid-cols-2">
              {report.phase_analysis.map((p) => {
                const phaseEvidence = evidence?.phases.find((x) => x.phase === p.phase);
                return (
                  <article
                    key={p.phase}
                    className={cn(
                      'flex flex-col gap-2 rounded-panel border border-rule bg-surface p-3',
                      activePhase === p.phase && 'border-accent',
                    )}
                  >
                    <h3 className="text-sm font-semibold text-text">
                      {PHASE_LABEL[p.phase] ?? p.phase}
                    </h3>
                    <p className="text-sm text-text">
                      {p.summary}{' '}
                      <EvidenceChips
                        ids={p.evidence}
                        index={index}
                        active={activeEvidence}
                        onSelect={select}
                      />
                    </p>
                    {phaseEvidence?.views.map((v) => (
                      <div key={v.camera_id} className="flex flex-col gap-1">
                        <div className="flex gap-1 overflow-x-auto">
                          {v.frames.map((f) =>
                            f.url ? (
                              <img
                                key={f.id}
                                src={f.url}
                                alt={`Frame ${f.id} from ${v.camera_id}`}
                                loading="lazy"
                                className={cn(
                                  'h-24 rounded-tile object-cover',
                                  activeEvidence === f.id && 'ring-2 ring-accent',
                                )}
                              />
                            ) : null,
                          )}
                        </div>
                        <ul className="flex flex-col gap-0.5 text-xs text-text-muted">
                          {v.vqa.map((qa) => (
                            <li key={qa.id} className={cn(activeEvidence === qa.id && 'text-text')}>
                              {qa.q} <strong className="font-medium text-text">{qa.a}</strong>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ))}
                  </article>
                );
              })}
            </div>
          </Section>

          {activeEvidence && (
            <aside
              aria-label="Selected evidence"
              className="rounded-panel border border-accent bg-accent-tint p-3 text-sm text-text print:hidden"
            >
              <p className="font-medium">{index.get(activeEvidence)?.kind ?? activeEvidence}</p>
              <p>{index.get(activeEvidence)?.text}</p>
              {frameFor(activeEvidence)?.url && (
                <img
                  src={frameFor(activeEvidence).url}
                  alt={`Evidence ${activeEvidence}`}
                  className="mt-2 max-h-60 rounded-tile"
                />
              )}
            </aside>
          )}

          <Section title="Scene">
            <p className="text-sm text-text">
              <strong className="font-medium">Where:</strong> {report.scene_understanding.location}.{' '}
              <strong className="font-medium">Conditions:</strong>{' '}
              {report.scene_understanding.conditions}.
            </p>
            {report.scene_understanding.actors.length > 0 && (
              <ul className="flex flex-col gap-1 text-sm text-text">
                {report.scene_understanding.actors.map((a) => (
                  <li key={a.ref} className="flex flex-wrap items-baseline gap-2">
                    <span>
                      <strong className="font-medium">{a.ref}:</strong> {a.description}
                    </span>
                    <EvidenceChips
                      ids={a.evidence}
                      index={index}
                      active={activeEvidence}
                      onSelect={select}
                    />
                  </li>
                ))}
              </ul>
            )}
          </Section>

          {report.causal_chain.length > 0 && (
            <Section title="How it unfolded">
              <ol className="flex flex-col gap-2 text-sm text-text">
                {report.causal_chain.map((s) => (
                  <li key={s.step} className="flex gap-3">
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-pill bg-accent-tint text-xs font-semibold text-accent">
                      {s.step}
                    </span>
                    <span>
                      {s.description}{' '}
                      <EvidenceChips
                        ids={s.evidence}
                        index={index}
                        active={activeEvidence}
                        onSelect={select}
                      />
                    </span>
                  </li>
                ))}
              </ol>
            </Section>
          )}

          {(report.contributing_factors.primary.length > 0 ||
            report.contributing_factors.environmental.length > 0 ||
            report.contributing_factors.security_gaps.length > 0) && (
            <Section title="Contributing factors">
              <FactorList
                title="Main"
                items={report.contributing_factors.primary}
                index={index}
                active={activeEvidence}
                onSelect={select}
              />
              <FactorList
                title="Environment"
                items={report.contributing_factors.environmental}
                index={index}
                active={activeEvidence}
                onSelect={select}
              />
              <FactorList
                title="Security gaps"
                items={report.contributing_factors.security_gaps}
                index={index}
                active={activeEvidence}
                onSelect={select}
              />
            </Section>
          )}

          {report.recommended_actions.length > 0 && (
            <Section title="Recommended actions">
              <ul className="flex flex-col gap-1 text-sm text-text">
                {report.recommended_actions.map((a) => (
                  <li key={a.action} className="flex flex-wrap items-baseline gap-2">
                    <span>{a.action}</span>
                    <span className="rounded-pill bg-surface-raised px-2 py-px text-xs capitalize text-text-muted">
                      {a.priority} priority · {a.owner_role}
                    </span>
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {report.limitations.length > 0 && (
            <Section title="What this report cannot tell">
              <ul className="list-disc pl-5 text-sm text-text-muted">
                {report.limitations.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            </Section>
          )}

          <p className="text-xs text-text-muted">{provenanceNote(incident.provenance)}</p>
        </>
      )}

      {similar.data?.items.length > 0 && (
        <Section title="Similar incidents">
          <ul className="flex flex-col divide-y divide-rule rounded-panel border border-rule">
            {similar.data.items.map((s) => (
              <li key={s.incident_id}>
                <Link
                  to={`/incidents/${s.incident_id}`}
                  className="flex flex-wrap items-center gap-2 p-2 hover:bg-surface-raised"
                >
                  {s.severity && <SeverityBadge severity={s.severity} />}
                  <span className="text-sm text-text">{s.title}</span>
                  <span className="ml-auto text-xs tabular-nums text-text-muted">
                    {s.camera_ids.join(', ')} · {Math.round(s.score * 100)}% alike
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {canEdit && report && (
        <Section title="Review">
          <div className="flex max-w-xl flex-col gap-2 print:hidden">
            <Textarea
              aria-label="Notes"
              placeholder="Notes for the next shift"
              value={notes ?? incident.notes ?? ''}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
            />
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={update.isPending || notes === null}
                onClick={() => update.mutate({ notes: notes ?? '' })}
              >
                Save notes
              </Button>
              {incident.status === 'generated' && (
                <Button
                  size="sm"
                  disabled={update.isPending}
                  onClick={() => update.mutate({ status: 'reviewed' })}
                >
                  Mark as reviewed
                </Button>
              )}
              {incident.status !== 'closed' && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={update.isPending}
                  onClick={() => update.mutate({ status: 'closed' })}
                >
                  Close incident
                </Button>
              )}
            </div>
            {update.isError && (
              <p role="alert" className="text-sm text-sev-critical">
                Could not save. Try again.
              </p>
            )}
          </div>
        </Section>
      )}
      <AddToCaseDialog item={saving} onClose={() => setSaving(null)} />
    </div>
  );
}
