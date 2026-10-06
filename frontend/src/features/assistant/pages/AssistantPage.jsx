import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { MessageSquarePlus, Send, Square, Trash2 } from 'lucide-react';
import { NavLink, useNavigate, useParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import {
  SESSIONS_KEY,
  sessionKey,
  useCreateSession,
  useDeleteSession,
  useSession,
  useSessions,
  useStarters,
} from '../api';
import { ChatMessage, ToolLines } from '../components/ChatMessage';
import { streamMessage } from '../stream';

const EMPTY_TURN = { question: '', tools: [], text: '', citations: [], error: null };

/** The assistant (FR-AST): ask in plain words; it looks things up in the system's records and
 * answers with the evidence behind each statement. Answers stream in; what it looked up shows
 * while it works; Stop ends a turn early and keeps what was written.
 */
export function AssistantPage() {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: sessions } = useSessions();
  const { data: session } = useSession(sessionId);
  const { data: starters } = useStarters();
  const create = useCreateSession();
  const remove = useDeleteSession();

  const [draft, setDraft] = useState('');
  const [turn, setTurn] = useState(null);
  const abortRef = useRef(null);
  const endRef = useRef(null);

  const messages = session?.messages ?? [];
  const busy = turn !== null;

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'end' });
  }, [messages.length, turn?.text, turn?.tools.length]);

  useEffect(() => () => abortRef.current?.abort(), []);

  async function send(question) {
    const content = question.trim();
    if (!content || busy) return;
    setDraft('');
    let id = sessionId;
    if (!id) {
      const created = await create.mutateAsync();
      id = created.id;
      navigate(`/assistant/${id}`, { replace: true });
    }
    setTurn({ ...EMPTY_TURN, question: content });
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await streamMessage(
        id,
        content,
        (event, data) => {
          setTurn((t) => {
            if (!t) return t;
            switch (event) {
              case 'tool_call':
                return { ...t, tools: [...t.tools, { tool: data.tool, summary: null }] };
              case 'tool_result':
                return {
                  ...t,
                  tools: t.tools.map((x, i) =>
                    i === t.tools.length - 1
                      ? { ...x, summary: data.summary, lines: data.lines, cites: data.cites }
                      : x,
                  ),
                };
              case 'token':
                return { ...t, text: t.text + data.text };
              case 'citation':
                return { ...t, citations: data.citations };
              case 'error':
                return { ...t, error: data.message };
              default:
                return t;
            }
          });
        },
        controller.signal,
      );
    } catch (error) {
      if (error?.name !== 'AbortError') {
        setTurn((t) => (t ? { ...t, error: error.message } : t));
        await new Promise((resolve) => setTimeout(resolve, 0));
      }
    } finally {
      abortRef.current = null;
      await queryClient.invalidateQueries({ queryKey: sessionKey(id) });
      await queryClient.invalidateQueries({ queryKey: SESSIONS_KEY });
      setTurn((t) => (t?.error ? t : null));
    }
  }

  function onKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      send(draft);
    }
  }

  return (
    <div className="flex h-full min-h-0">
      <aside
        aria-label="Conversations"
        className="flex w-64 shrink-0 flex-col gap-2 border-r border-rule bg-surface p-3"
      >
        <Button size="sm" variant="outline" onClick={() => navigate('/assistant')}>
          <MessageSquarePlus size={14} aria-hidden="true" />
          New conversation
        </Button>
        <ul className="flex min-h-0 flex-1 flex-col gap-1 overflow-auto">
          {(sessions?.items ?? []).map((s) => (
            <li key={s.id} className="group flex items-center">
              <NavLink
                to={`/assistant/${s.id}`}
                className={({ isActive }) =>
                  cn(
                    'min-w-0 flex-1 truncate rounded-panel px-2 py-1.5 text-sm text-text-muted hover:bg-surface-raised hover:text-text',
                    isActive && 'bg-surface-raised text-text',
                  )
                }
              >
                {s.title}
              </NavLink>
              <button
                type="button"
                aria-label={`Delete conversation ${s.title}`}
                className="rounded-tile p-1 text-text-muted opacity-0 hover:text-sev-critical focus:opacity-100 group-hover:opacity-100"
                onClick={async () => {
                  await remove.mutateAsync(s.id);
                  if (s.id === sessionId) navigate('/assistant');
                }}
              >
                <Trash2 size={14} aria-hidden="true" />
              </button>
            </li>
          ))}
          {sessions && sessions.items.length === 0 && (
            <li className="px-2 text-xs text-text-muted">No conversations yet.</li>
          )}
        </ul>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col">
        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto p-4" aria-live="polite">
          {messages.length === 0 && !busy && (
            <div className="m-auto flex max-w-xl flex-col gap-3 text-center">
              <h1 className="text-xl font-semibold text-text">Ask about your cameras</h1>
              <p className="text-sm text-text-muted">
                I look things up in the recorded footage, events, incident reports and people
                counts, and show what each answer is based on.
              </p>
              <ul className="flex flex-col gap-2">
                {(starters?.questions ?? []).map((q) => (
                  <li key={q}>
                    <button
                      type="button"
                      onClick={() => send(q)}
                      className="w-full rounded-panel border border-rule px-3 py-2 text-left text-sm text-text hover:border-accent hover:text-accent"
                    >
                      {q}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {messages.map((m) => (
            <ChatMessage
              key={m.id}
              author={m.role}
              content={m.content}
              citations={m.citations}
              tools={m.tools}
              status={m.status}
            />
          ))}

          {busy && (
            <>
              {!messages.some((m) => m.role === 'user' && m.content === turn.question) && (
                <ChatMessage author="user" content={turn.question} />
              )}
              {turn.error ? (
                <p role="alert" className="max-w-3xl text-sm text-sev-critical">
                  {turn.error}{' '}
                  <button
                    type="button"
                    className="text-accent hover:underline"
                    onClick={() => {
                      const q = turn.question;
                      setTurn(null);
                      send(q);
                    }}
                  >
                    Try again
                  </button>
                </p>
              ) : (
                <>
                  {turn.text ? (
                    <ChatMessage
                      author="assistant"
                      content={turn.text}
                      citations={turn.citations}
                      tools={turn.tools}
                      streaming
                    />
                  ) : (
                    <div className="flex flex-col gap-2" role="status">
                      <ToolLines tools={turn.tools.filter((t) => t.summary != null)} />
                      <p className="text-sm text-text-muted">
                        {turn.tools.some((t) => t.summary == null)
                          ? `Looking up ${turn.tools.at(-1).tool?.replace(/_/g, ' ')}…`
                          : turn.tools.length
                            ? 'Writing the answer…'
                            : 'Thinking…'}
                      </p>
                    </div>
                  )}
                </>
              )}
            </>
          )}
          <div ref={endRef} />
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            send(draft);
          }}
          className="flex items-end gap-2 border-t border-rule bg-surface p-3"
        >
          <Textarea
            aria-label="Ask a question"
            placeholder="For example: what happened on cam01 in the last hour?"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            rows={2}
            className="min-h-0 flex-1 resize-none"
          />
          {busy ? (
            <Button type="button" variant="outline" onClick={() => abortRef.current?.abort()}>
              <Square size={14} aria-hidden="true" />
              Stop
            </Button>
          ) : (
            <Button type="submit" disabled={!draft.trim()}>
              <Send size={14} aria-hidden="true" />
              Send
            </Button>
          )}
        </form>
      </section>
    </div>
  );
}
