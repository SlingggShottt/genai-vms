import { useLayoutEffect, useRef } from 'react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

/** "Are you sure?" for something that can't be undone. The confirm button names the action
 * (§B.8: "Delete zone", not "OK"); focus goes back to whatever opened it.
 *
 * Controlled: the parent sets `open`, runs the action in `onConfirm`, and decides when to close
 * (so it can stay open and show `error` if the request fails).
 */
export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  onConfirm,
  onClose,
  isPending = false,
  error = null,
}) {
  const opener = useRef(null);

  // Radix only restores focus for a `Trigger`; this dialog is opened by state from a button in
  // another component. A layout effect runs before Radix moves focus into the dialog.
  useLayoutEffect(() => {
    if (open) opener.current = document.activeElement;
  }, [open]);

  function restoreFocus(event) {
    const target = opener.current;
    opener.current = null;
    if (target?.isConnected) {
      event.preventDefault();
      target.focus();
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && !isPending && onClose()}>
      <DialogContent onCloseAutoFocus={restoreFocus}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        {error && (
          <p role="alert" className="text-sm text-sev-critical">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose} disabled={isPending}>
            Cancel
          </Button>
          <Button type="button" onClick={onConfirm} disabled={isPending}>
            {isPending ? 'Working…' : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
