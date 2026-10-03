import { useState } from 'react';

/** The event's keyframes (presigned urls, good for 15 minutes). If one cannot be loaded — most
 * likely because the page has been open past that — say so and how to fix it, instead of
 * showing a broken image.
 *
 * @param {{urls: string[], count: number, camera: string}} props  `count` is how many the event
 *   has, which can exceed `urls.length` only if the api sent none (then there is nothing to show)
 */
export function KeyframeStrip({ urls, count, camera }) {
  const [failed, setFailed] = useState(() => new Set());

  if (count === 0) {
    return <p className="text-sm text-text-muted">This event has no keyframes.</p>;
  }
  if (urls.length === 0) {
    return <p className="text-sm text-text-muted">Keyframes are not available right now.</p>;
  }

  return (
    <div className="flex flex-col gap-2">
      <ul className="grid grid-cols-2 gap-2">
        {urls.map((url, index) => (
          <li key={url} className="overflow-hidden rounded-tile bg-video-bg">
            {failed.has(url) ? (
              <p className="flex aspect-video items-center justify-center p-3 text-center text-xs text-text-muted">
                Keyframe {index + 1} could not be loaded.
              </p>
            ) : (
              <img
                src={url}
                alt={`Keyframe ${index + 1} of ${urls.length} from ${camera}`}
                loading="lazy"
                onError={() => setFailed((prev) => new Set(prev).add(url))}
                className="aspect-video w-full object-cover"
              />
            )}
          </li>
        ))}
      </ul>
      {failed.size > 0 && (
        <p className="text-xs text-text-muted">
          Keyframe links expire after 15 minutes. Reload the page to get fresh ones.
        </p>
      )}
    </div>
  );
}
