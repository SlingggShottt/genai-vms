/** MediaMTX playback URLs and a raw WHEP client (docs/design_architecture.md
 * §16: path naming `rtsp://…/cam{n}`, same path serves HLS and WHEP). No
 * WHEP client library exists for this — the protocol is a single
 * offer/answer HTTP exchange, small enough to implement directly rather
 * than pull in a dependency for it (style_guide.md doesn't list one).
 */
const WEBRTC_BASE = import.meta.env.VITE_MEDIAMTX_WEBRTC_URL || 'http://localhost:8889';
const HLS_BASE = import.meta.env.VITE_MEDIAMTX_HLS_URL || 'http://localhost:8888';

export function hlsUrl(cameraCode) {
  return `${HLS_BASE}/${cameraCode}/index.m3u8`;
}

function whepUrl(cameraCode) {
  return `${WEBRTC_BASE}/${cameraCode}/whep`;
}

/** Opens a WHEP (WebRTC-HTTP Egress Protocol) session against MediaMTX and
 * attaches the incoming stream to `videoEl`. Returns a `close()` function
 * that tears down the peer connection and releases the server-side session
 * (`DELETE` on the resource URL the server handed back) — callers must call
 * it on unmount/camera-switch or the session leaks on the MediaMTX side.
 *
 * Throws if the offer/answer exchange fails (camera not publishing, network
 * error, non-2xx response) — callers should catch this and fall back to
 * `hlsUrl()` + hls.js, per FR-LIVE-01.
 *
 * A session that negotiated fine can still die afterwards — MediaMTX closes
 * it straight away for an H.264 stream with B-frames (WebRTC can't carry
 * them), and the browser only reports the connection `failed` ~15 s later.
 * `onConnectionLost` is called once if the connection reaches `failed` or
 * `closed` on its own (never after the caller's own `close()`), so the caller
 * can fall back to HLS here too.
 */
export async function connectWhep(videoEl, cameraCode, { signal, onConnectionLost } = {}) {
  const pc = new RTCPeerConnection({ iceServers: [] });
  const stream = new MediaStream();
  videoEl.srcObject = stream;

  let closed = false;
  let lostReported = false;
  pc.onconnectionstatechange = () => {
    if (closed || lostReported) return;
    if (pc.connectionState === 'failed' || pc.connectionState === 'closed') {
      lostReported = true;
      onConnectionLost?.();
    }
  };

  pc.ontrack = (event) => {
    stream.addTrack(event.track);
  };

  // recvonly: we're a viewer, never publishing back to MediaMTX.
  pc.addTransceiver('video', { direction: 'recvonly' });
  pc.addTransceiver('audio', { direction: 'recvonly' });

  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);

  // WHEP negotiates on a single request: POST the SDP offer, get the SDP
  // answer back in the body and the session's own resource URL in
  // `Location` (used only to DELETE it on close, per the WHEP spec).
  const response = await fetch(whepUrl(cameraCode), {
    method: 'POST',
    headers: { 'Content-Type': 'application/sdp' },
    body: offer.sdp,
    signal,
  });

  if (!response.ok) {
    pc.close();
    throw new Error(`WHEP offer rejected (${response.status}) for camera ${cameraCode}.`);
  }

  const answerSdp = await response.text();
  const location = response.headers.get('Location');
  const resourceUrl = location ? new URL(location, whepUrl(cameraCode)).toString() : null;

  await pc.setRemoteDescription({ type: 'answer', sdp: answerSdp });

  return function close() {
    if (closed) return;
    closed = true;
    pc.close();
    // Only release the element if it's still ours: after a fallback to HLS the
    // caller has already cleared it, and clearing `srcObject` again would
    // reset whatever is playing now.
    if (videoEl.srcObject === stream) videoEl.srcObject = null;
    if (resourceUrl) {
      // Best-effort: the session will also expire server-side on its own,
      // this just frees it immediately. Never block teardown on it.
      fetch(resourceUrl, { method: 'DELETE' }).catch(() => {});
    }
  };
}
