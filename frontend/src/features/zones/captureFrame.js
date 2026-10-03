/** Grabs the picture a `<video>` is showing right now as a JPEG, at the stream's own resolution
 * (not the size it happens to be drawn at), so a zone drawn on it lines up with every later frame.
 *
 * The api has no snapshot endpoint yet (design_architecture.md §9 lists
 * `GET /cameras/{id}/snapshot`), so the zone editor takes its picture from the live view.
 * Rejects with a message for the operator when there is no picture to take.
 */
export class NoPictureError extends Error {}

const HAVE_CURRENT_DATA = 2;

export function captureFrame(
  video,
  { quality = 0.85, createCanvas = () => document.createElement('canvas') } = {},
) {
  return new Promise((resolve, reject) => {
    const width = video?.videoWidth ?? 0;
    const height = video?.videoHeight ?? 0;
    if (!video || video.readyState < HAVE_CURRENT_DATA || !width || !height) {
      reject(
        new NoPictureError('No picture yet. Wait for the stream to start, then capture again.'),
      );
      return;
    }
    const canvas = createCanvas();
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext('2d');
    if (!context) {
      reject(new NoPictureError("This browser can't capture a frame. Try another browser."));
      return;
    }
    try {
      context.drawImage(video, 0, 0, width, height);
    } catch {
      // A tainted source (a cross-origin stream without CORS) refuses to be read back.
      reject(
        new NoPictureError(
          "The stream can't be captured from this page. Check the camera feed's CORS settings.",
        ),
      );
      return;
    }
    canvas.toBlob(
      (blob) =>
        blob
          ? resolve({ blob, width, height })
          : reject(new NoPictureError('Could not capture the frame. Try again.')),
      'image/jpeg',
      quality,
    );
  });
}
