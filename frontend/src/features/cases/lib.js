/** Where a case item leads. Events resolve to their alert page at click time (the UI addresses
 * events by alert id), so they have no static link. */
export function itemHref(item) {
  switch (item.kind) {
    case 'incident':
      return `/incidents/${item.ref}`;
    case 'footage': {
      if (!item.camera_id || !item.ts_start) return null;
      const start = new Date(item.ts_start);
      const end = item.ts_end ? new Date(item.ts_end) : new Date(start.getTime() + 15000);
      const params = new URLSearchParams({
        camera: item.camera_id,
        start: start.toISOString(),
        end: end.toISOString(),
      });
      return `/playback?${params.toString()}`;
    }
    case 'search':
      return `/search?${new URLSearchParams({ q: item.ref ?? item.label }).toString()}`;
    default:
      return null;
  }
}

export const KIND_LABEL = {
  event: 'Event',
  incident: 'Incident report',
  footage: 'Footage',
  search: 'Search',
  note: 'Note',
};
