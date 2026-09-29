/** Placeholder for P1-J5 (live camera wall — WebRTC/HLS tiles, status dots,
 * layout switcher). This route exists so the app shell has somewhere to
 * land after login; the real tile grid replaces this component.
 */
export function LiveWallPage() {
  return (
    <div className="flex h-full items-center justify-center text-center text-text-muted">
      <div>
        <p className="text-base text-text">Live camera wall</p>
        <p className="mt-1 text-sm">Coming in P1-J5.</p>
      </div>
    </div>
  );
}
