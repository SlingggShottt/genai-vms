import { useEffect, useRef, useState } from 'react';
import Hls from 'hls.js';
import { hlsAuthConfig, playlistUrl } from '@/features/playback/api';

/** Plays the recording of one camera between two instants (the playlist endpoint of
 * services/api, `GET /recordings/{camera}/playlist.m3u8`) — an event's clip. hls.js loads the
 * manifest itself, so it needs the same auth hook the Playback page uses.
 *
 * @param {{cameraCode: string, startIso: string, endIso: string}} props
 */
export function ClipPlayer({ cameraCode, startIso, endIso }) {
  const videoRef = useRef(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !cameraCode) return undefined;
    setError(null);
    const url = playlistUrl(cameraCode, startIso, endIso);
    let hls = null;
    let cancelled = false;

    if (Hls.isSupported()) {
      hls = new Hls(hlsAuthConfig());
      hls.on(Hls.Events.ERROR, (_event, data) => {
        if (data.fatal && !cancelled) {
          setError('Playback failed. The recording may not cover this time.');
        }
      });
      hls.loadSource(url);
      hls.attachMedia(video);
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = url;
    } else {
      setError('This browser cannot play HLS video.');
    }

    return () => {
      cancelled = true;
      hls?.destroy();
    };
  }, [cameraCode, startIso, endIso]);

  return (
    <div className="flex flex-col gap-2">
      {/* Black behind video only, 2 px radius: a monitor (§B.5). */}
      <video
        ref={videoRef}
        controls
        muted
        playsInline
        aria-label={`Recording of ${cameraCode}`}
        className="aspect-video w-full rounded-tile bg-video-bg"
      />
      {error && (
        <p role="alert" className="text-sm text-sev-critical">
          {error}
        </p>
      )}
    </div>
  );
}
