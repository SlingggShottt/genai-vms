import { Toaster as Sonner } from 'sonner';

/** Toasts themed through the tokens (floating layer: shadow allowed, §B.5). Messages repeat the
 * name of the action the operator took: *Acknowledge* -> "Alert acknowledged" (§B.8).
 */
export function Toaster(props) {
  return (
    <Sonner
      theme="dark"
      position="bottom-left"
      style={{
        '--normal-bg': 'var(--surface-raised)',
        '--normal-text': 'var(--text)',
        '--normal-border': 'var(--rule)',
        '--success-bg': 'var(--surface-raised)',
        '--success-text': 'var(--text)',
        '--success-border': 'var(--ok)',
        '--error-bg': 'var(--surface-raised)',
        '--error-text': 'var(--text)',
        '--error-border': 'var(--sev-critical)',
      }}
      {...props}
    />
  );
}
