import { apiUrl, refreshAccessToken } from '@/lib/apiClient';
import { getAccessToken } from '@/lib/tokenStore';

/** Parse a server-sent-events body into `{event, data}` objects. Pure; exported for tests. */
export function parseSse(buffer) {
  const events = [];
  let rest = buffer;
  let cut;
  while ((cut = rest.indexOf('\n\n')) !== -1) {
    const block = rest.slice(0, cut);
    rest = rest.slice(cut + 2);
    let event = 'message';
    const data = [];
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim();
      else if (line.startsWith('data:')) data.push(line.slice(5).trim());
    }
    if (data.length) {
      try {
        events.push({ event, data: JSON.parse(data.join('\n')) });
      } catch {
        // a malformed block is skipped, not fatal
      }
    }
  }
  return { events, rest };
}

async function post(path, body, signal) {
  return fetch(apiUrl(path), {
    method: 'POST',
    signal,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${getAccessToken()}`,
    },
    body: JSON.stringify(body),
  });
}

/** POST a message and call `onEvent` for every streamed event. Resolves when the stream ends;
 * aborting `signal` (the stop button) ends it early. Refreshes the token once on a 401. */
export async function streamMessage(sessionId, content, onEvent, signal) {
  const path = `/assistant/sessions/${sessionId}/messages`;
  let response = await post(path, { content }, signal);
  if (response.status === 401) {
    await refreshAccessToken();
    response = await post(path, { content }, signal);
  }
  if (!response.ok || !response.body) {
    let message = 'The assistant could not answer. Try again.';
    try {
      message = (await response.json())?.error?.message ?? message;
    } catch {
      // keep the default
    }
    throw new Error(message);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parsed = parseSse(buffer);
    buffer = parsed.rest;
    for (const item of parsed.events) onEvent(item.event, item.data);
  }
}
