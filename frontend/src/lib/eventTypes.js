const LABELS = {
  intrusion: 'Intrusion',
  loitering: 'Loitering',
  crowding: 'Crowding',
  abandoned_object: 'Abandoned object',
  running: 'Running',
};

/** Sentence-case name for an event type (§B.8). An unknown type (a rule added on the server)
 * is tidied rather than hidden: `fire-door_open` -> "Fire door open".
 */
export function eventTypeLabel(type) {
  if (LABELS[type]) return LABELS[type];
  const text = String(type ?? '')
    .replace(/[_-]+/g, ' ')
    .trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : 'Event';
}
