import { useRef, useState } from 'react';
import { Camera } from 'lucide-react';
import { VideoTile } from '@/components/VideoTile';
import { Button } from '@/components/ui/button';
import { captureFrame } from '../captureFrame';

/** The camera's live view with a "Capture frame" button: the zone editor draws on that still.
 * `onCapture({ url, width, height })` gets a blob URL that the caller owns and must revoke.
 */
export function FrameCapture({ camera, status, onCapture, hint }) {
  const videoElRef = useRef(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function handleCapture() {
    setError(null);
    setBusy(true);
    try {
      const { blob, width, height } = await captureFrame(videoElRef.current);
      onCapture({ url: URL.createObjectURL(blob), width, height });
    } catch (captureError) {
      setError(captureError.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <VideoTile camera={{ ...camera, status }} videoElRef={videoElRef} />
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <Button type="button" size="sm" onClick={handleCapture} disabled={busy}>
          <Camera size={16} aria-hidden="true" />
          Capture frame
        </Button>
        {hint && <p className="text-sm text-text-muted">{hint}</p>}
      </div>
      {error && (
        <p role="alert" className="mt-2 text-sm text-sev-critical">
          {error}
        </p>
      )}
    </div>
  );
}
