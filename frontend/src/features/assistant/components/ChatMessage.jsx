import { Fragment } from 'react';
import { cn } from '@/lib/utils';
import { CitationChip } from './CitationChip';

const TAG = /\[([EIS]):([0-9a-zA-Z_-]{4,40})\]/g;

/** Split answer text into plain text and the citations it names. A tag the server did not hand
 * out (no matching citation) is dropped from the text: it is not evidence. */
export function segments(text, citations) {
  const byKey = new Map(citations.map((c) => [`${c.kind}:${c.tag}`, c]));
  const out = [];
  let last = 0;
  for (const m of text.matchAll(TAG)) {
    if (m.index > last) out.push({ text: text.slice(last, m.index) });
    const citation = byKey.get(`${m[1]}:${m[2]}`);
    if (citation && !citation.consulted) out.push({ citation });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last) });
  return out;
}

/** Render a line of tool output, turning its [E:…]/[I:…]/[S:…] tags into the citation chips the
 * message carries (a tag nobody handed out stays plain text). */
function FoundLine({ line, citations }) {
  return (
    <>
      {segments(
        line,
        citations.map((c) => ({ ...c, consulted: false })),
      ).map((seg, i) =>
        seg.citation ? (
          <Fragment key={i}>
            {' '}
            <CitationChip citation={seg.citation} />{' '}
          </Fragment>
        ) : (
          <Fragment key={i}>{seg.text}</Fragment>
        ),
      )}
    </>
  );
}

/** What the assistant looked up and what the records said, so the figures are in front of the
 * reader whatever the wording of the answer. */
export function ToolLines({ tools, citations = [] }) {
  if (!tools?.length) return null;
  return (
    <ul
      aria-label="What the assistant looked up"
      className="flex flex-col gap-1 text-xs text-text-muted"
    >
      {tools.map((t, i) => (
        <li key={`${t.tool}-${i}`}>
          <details open={i === tools.length - 1}>
            <summary className="cursor-pointer">
              Looked up{' '}
              <span className="font-condensed text-text">{t.tool?.replace(/_/g, ' ')}</span>
              {t.summary ? ` — ${t.summary.replace(/\[[EIS]:[^\]]+\]\s*/g, '')}` : ''}
            </summary>
            {t.lines?.length > 0 && (
              <ul className="mt-1 flex flex-col gap-1 border-l border-rule pl-3 text-text">
                {t.lines.map((line, k) => (
                  <li key={k}>
                    <FoundLine line={line} citations={t.cites ?? citations} />
                  </li>
                ))}
              </ul>
            )}
          </details>
        </li>
      ))}
    </ul>
  );
}

/** One turn. The operator's is a plain bubble; the assistant's shows what it looked up, the
 * answer with citation chips inline, and — when the model cited nothing — the records it
 * consulted, labelled as such. */
export function ChatMessage({
  author,
  content,
  citations = [],
  tools = [],
  status,
  streaming,
  allCitations = citations,
}) {
  const consulted = citations.filter((c) => c.consulted);
  const user = author === 'user';
  return (
    <article
      aria-label={user ? 'You' : 'Assistant'}
      className={cn('flex max-w-3xl flex-col gap-2', user ? 'self-end' : 'self-start')}
    >
      <div
        className={cn(
          'rounded-panel px-3 py-2 text-sm',
          user ? 'bg-accent text-accent-ink' : 'border border-rule bg-surface text-text',
        )}
      >
        {user ? (
          content
        ) : (
          <>
            <p className="whitespace-pre-wrap leading-relaxed">
              {segments(content, citations).map((seg, i) => (
                <Fragment key={i}>
                  {seg.citation ? (
                    <>
                      {' '}
                      <CitationChip citation={seg.citation} />
                    </>
                  ) : (
                    seg.text
                  )}
                </Fragment>
              ))}
              {streaming && (
                <span
                  className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-text-muted align-middle"
                  aria-hidden="true"
                />
              )}
            </p>
            {status === 'stopped' && (
              <p className="mt-1 text-xs text-text-muted">Stopped before it finished.</p>
            )}
            {status === 'failed' && (
              <p className="mt-1 text-xs text-sev-critical">The answer could not be completed.</p>
            )}
          </>
        )}
      </div>
      {!user && <ToolLines tools={tools} citations={allCitations} />}
      {!user && consulted.length > 0 && (
        <div className="flex flex-wrap items-center gap-1 text-xs text-text-muted">
          <span>Records consulted:</span>
          {consulted.map((c) => (
            <CitationChip key={`${c.kind}:${c.tag}`} citation={c} />
          ))}
        </div>
      )}
    </article>
  );
}
