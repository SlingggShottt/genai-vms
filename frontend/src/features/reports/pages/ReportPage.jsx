import { Link, useParams } from 'react-router-dom';
import { Printer } from 'lucide-react';
import { SeverityBadge } from '@/components/SeverityBadge';
import { PdfButton } from '@/components/PdfButton';
import { Button } from '@/components/ui/button';
import { ApiError } from '@/lib/apiClient';
import { eventTypeLabel } from '@/lib/eventTypes';
import { useReport } from '../api';
import { HorizontalBars, HourColumns } from '../components/Bars';
import { formatSeconds, hourSeries, periodLabel } from '../lib';

function Tile({ label, value, note }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-panel border border-rule bg-surface p-3">
      <span className="text-xs text-text-muted">{label}</span>
      <span className="text-xl font-semibold tabular-nums text-text">{value}</span>
      {note && <span className="text-xs text-text-muted">{note}</span>}
    </div>
  );
}

function Section({ title, children }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-base font-semibold text-text">{title}</h2>
      {children}
    </section>
  );
}

const rows = (record, label = (k) => k) =>
  Object.entries(record ?? {}).map(([name, value]) => ({ name: label(name), value }));

/** One daily report: the written summary, the headline figures, charts, the incident reports it
 * covers and the response times. Print or save as PDF from the browser (the layout is print-ready).
 */
export function ReportPage() {
  const { reportId } = useParams();
  const { data: report, isLoading, isError, error } = useReport(reportId);

  if (isLoading) return <p className="p-4 text-sm text-text-muted">Loading report…</p>;
  if (isError || !report) {
    const missing = error instanceof ApiError && [400, 404].includes(error.status);
    return (
      <div className="flex flex-col items-start gap-2 p-4 text-sm text-text-muted">
        <p>{missing ? 'This report was not found.' : 'Could not load this report. Try again.'}</p>
        <Link to="/reports" className="text-accent hover:underline">
          All reports
        </Link>
      </div>
    );
  }

  const f = report.facts;
  const high = f ? (f.by_severity.high ?? 0) + (f.by_severity.critical ?? 0) : 0;

  return (
    <div className="flex h-full flex-col gap-5 overflow-auto p-4 print:overflow-visible">
      <Link to="/reports" className="text-sm text-accent hover:underline print:hidden">
        All reports
      </Link>
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold text-text">
          Daily security report · {periodLabel(report)}
        </h1>
        {report.status === 'ready' && (
          <div className="ml-auto flex gap-2 print:hidden">
            <PdfButton path={`/reports/daily/${report.id}/pdf`} available={report.has_pdf} />
            <Button size="sm" variant="outline" onClick={() => window.print()}>
              <Printer size={14} aria-hidden="true" />
              Print or save as PDF
            </Button>
          </div>
        )}
      </header>

      {(report.status === 'queued' || report.status === 'generating') && (
        <p role="status" className="rounded-panel border border-rule p-3 text-sm text-text-muted">
          {report.status === 'queued' ? 'Waiting for the worker…' : 'Writing the report…'} This page
          updates by itself.
        </p>
      )}
      {report.status === 'failed' && (
        <p
          role="alert"
          className="rounded-panel border border-sev-critical p-3 text-sm text-sev-critical"
        >
          The report could not be written{report.error ? `: ${report.error}` : ''}.
        </p>
      )}

      {f && (
        <>
          {report.narrative && (
            <div className="flex max-w-3xl flex-col gap-1">
              <p className="whitespace-pre-line text-base text-text">{report.narrative}</p>
              <p className="text-xs text-text-muted">
                {report.narrative_source === 'llm'
                  ? 'Written by the language model; every number in it was checked against the figures below.'
                  : 'Standard summary built directly from the figures below (the language model’s text could not be matched to them).'}
              </p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Tile
              label="Verified events"
              value={f.events_total}
              note={`${f.events_rejected} false alarms filtered`}
            />
            <Tile label="High severity or above" value={high} />
            <Tile label="Incident reports" value={f.incidents_total} />
            <Tile
              label="Alerts"
              value={f.alerts_total}
              note={f.alerts_open ? `${f.alerts_open} still open` : 'none open'}
            />
          </div>

          <Section title="Events by hour (IST)">
            <HourColumns series={hourSeries(f.by_hour)} label="Events by hour of day" />
          </Section>

          <div className="grid gap-6 md:grid-cols-3">
            <Section title="By type">
              <HorizontalBars rows={rows(f.by_type, eventTypeLabel)} label="Events by type" />
            </Section>
            <Section title="By camera">
              <HorizontalBars rows={rows(f.by_camera)} label="Events by camera" />
            </Section>
            <Section title="By severity">
              <HorizontalBars
                rows={rows(f.by_severity, (s) => s.charAt(0).toUpperCase() + s.slice(1))}
                label="Events by severity"
              />
            </Section>
          </div>

          <div className="grid gap-6 md:grid-cols-2">
            <Section title="Response times">
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
                <dt className="text-text-muted">Acknowledged, median</dt>
                <dd className="tabular-nums text-text">{formatSeconds(f.ack_p50_s)}</dd>
                <dt className="text-text-muted">Acknowledged, 90th percentile</dt>
                <dd className="tabular-nums text-text">{formatSeconds(f.ack_p90_s)}</dd>
                <dt className="text-text-muted">Resolved, median</dt>
                <dd className="tabular-nums text-text">{formatSeconds(f.resolve_p50_s)}</dd>
                <dt className="text-text-muted">Resolved, 90th percentile</dt>
                <dd className="tabular-nums text-text">{formatSeconds(f.resolve_p90_s)}</dd>
              </dl>
            </Section>
            <Section title="Crowd and linking">
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
                {Object.entries(f.people_peak_by_camera).map(([cam, n]) => (
                  <div key={cam} className="contents">
                    <dt className="text-text-muted">Most people at once, {cam}</dt>
                    <dd className="tabular-nums text-text">{n}</dd>
                  </div>
                ))}
                <dt className="text-text-muted">Events linked across cameras</dt>
                <dd className="tabular-nums text-text">
                  {f.groups_multi_camera} of {f.groups_total} groups
                </dd>
              </dl>
            </Section>
          </div>

          <Section title={`Incident reports (${f.incidents_total})`}>
            {f.incidents.length === 0 ? (
              <p className="text-sm text-text-muted">No incident reports in this period.</p>
            ) : (
              <ul className="flex flex-col divide-y divide-rule rounded-panel border border-rule">
                {f.incidents.map((i) => (
                  <li key={i.id}>
                    <Link
                      to={`/incidents/${i.id}`}
                      className="flex flex-wrap items-center gap-2 p-2 hover:bg-surface-raised"
                    >
                      <SeverityBadge severity={i.severity} />
                      <span className="text-sm text-text">{i.title}</span>
                      <span className="ml-auto text-xs tabular-nums text-text-muted">
                        {eventTypeLabel(i.event_type)} · {i.cameras.join(', ')} · {i.at}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Section>
        </>
      )}
    </div>
  );
}
