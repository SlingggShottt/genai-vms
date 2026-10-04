import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { ApiError } from '@/lib/apiClient';
import { useAlertAction } from '../api';

export const NOTE_MAX = 1000;

// The button keeps the name of the action through the whole flow (§B.8).
const COPY = {
  acknowledge: { title: 'Acknowledge alert', button: 'Acknowledge', done: 'Alert acknowledged' },
  resolve: { title: 'Resolve alert', button: 'Resolve', done: 'Alert resolved' },
};

/** Says what went wrong and what to do about it (§B.8): no apologies, no jargon. */
export function actionErrorMessage(error, action) {
  if (error instanceof ApiError && error.status === 409) {
    const now = error.details?.status;
    return now
      ? `This alert is already ${now}, so it cannot be ${action === 'acknowledge' ? 'acknowledged' : 'resolved'} again. The list has been refreshed.`
      : 'This alert changed while you were acting on it. The list has been refreshed.';
  }
  if (error instanceof ApiError && error.status === 404) {
    return 'This alert no longer exists. The list has been refreshed.';
  }
  if (error instanceof ApiError && error.status === 403) {
    return 'Only operators and admins can act on alerts.';
  }
  return `Could not ${action} the alert. Check your connection and try again.`;
}

/**
 * @param {object} props
 * @param {'acknowledge'|'resolve'|null} props.action  null = closed
 * @param {object|null} props.alert
 * @param {() => void} props.onClose
 */
export function AlertNoteDialog({ action, alert, onClose }) {
  const [note, setNote] = useState('');
  const mutation = useAlertAction();
  const opener = useRef(null);

  // Whoever opened the dialog gets focus back when it closes (§B.10: alert actions are keyboard
  // operable). Radix only does this for a `Trigger`; this dialog is opened by state, from a button
  // in another component. A layout effect runs before Radix moves focus into the dialog.
  useLayoutEffect(() => {
    if (action) opener.current = document.activeElement;
  }, [action, alert?.id]);

  function restoreFocus(event) {
    const target = opener.current;
    opener.current = null;
    // The button may be gone (an acknowledged alert no longer offers Acknowledge); focusing a
    // detached element does nothing and focus falls back to the page, as it would by default.
    if (target) {
      event.preventDefault();
      target.focus();
    }
  }

  // A fresh dialog each time it opens: no note, no old error.
  useEffect(() => {
    if (action) {
      setNote('');
      mutation.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset only when it (re)opens
  }, [action, alert?.id]);

  if (!action || !alert) return null;
  const copy = COPY[action];

  function submit(event) {
    event.preventDefault();
    mutation.mutate(
      { id: alert.id, action, note },
      {
        onSuccess: () => {
          toast.success(copy.done);
          onClose();
        },
      },
    );
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !mutation.isPending && onClose()}>
      <DialogContent onCloseAutoFocus={restoreFocus}>
        <form onSubmit={submit} className="flex flex-col gap-4">
          <DialogHeader>
            <DialogTitle>{copy.title}</DialogTitle>
            <DialogDescription>
              {alert.title}, {alert.camera_code}
            </DialogDescription>
          </DialogHeader>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="alert-note">Note (optional)</Label>
            <Textarea
              id="alert-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={NOTE_MAX}
              placeholder="What you saw or what you did"
              // eslint-disable-next-line jsx-a11y/no-autofocus -- a dialog opened on purpose: the note is the one field
              autoFocus
            />
          </div>

          {mutation.isError && (
            <p role="alert" className="text-sm text-sev-critical">
              {actionErrorMessage(mutation.error, action)}
            </p>
          )}

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onClose} disabled={mutation.isPending}>
              Cancel
            </Button>
            <Button type="submit" disabled={mutation.isPending}>
              {copy.button}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
