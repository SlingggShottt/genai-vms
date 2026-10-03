import { useState } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import userEvent from '@testing-library/user-event';
import { toast } from 'sonner';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, apiClient } from '@/lib/apiClient';
import { clearTokens } from '@/lib/tokenStore';
import { makeQueryClient, renderWithProviders, stubApi } from '@/test/utils';
import open from '../fixtures/alert_open.json';
import { AlertNoteDialog, NOTE_MAX, actionErrorMessage } from './AlertNoteDialog';

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() }, Toaster: () => null }));
vi.mock('@/lib/apiClient', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, apiClient: { get: vi.fn(), post: vi.fn() } };
});

const acked = { ...open, status: 'acknowledged', ack_note: 'on my way' };

function renderDialog(action = 'acknowledge', onClose = vi.fn()) {
  const view = renderWithProviders(
    <AlertNoteDialog action={action} alert={open} onClose={onClose} />,
  );
  return { ...view, onClose };
}

describe('AlertNoteDialog', () => {
  beforeEach(() => {
    clearTokens();
    vi.mocked(toast.success).mockReset();
    vi.mocked(apiClient.post).mockReset();
    vi.mocked(apiClient.get).mockReset();
  });

  it('renders nothing while closed', () => {
    const { container } = renderWithProviders(
      <AlertNoteDialog action={null} alert={null} onClose={() => {}} />,
    );
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('names the action and the alert, and keeps that name on the button (§B.8)', () => {
    renderDialog('acknowledge');
    expect(screen.getByRole('dialog', { name: 'Acknowledge alert' })).toBeInTheDocument();
    expect(screen.getByText('Intrusion on cam02, cam02')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Acknowledge' })).toBeInTheDocument();
  });

  it('posts the trimmed note to /ack, confirms with a toast and closes', async () => {
    stubApi(apiClient, { [`POST /alerts/${open.id}/ack`]: acked });
    const { onClose } = renderDialog('acknowledge');

    await userEvent.type(screen.getByLabelText('Note (optional)'), '  on my way  ');
    await userEvent.click(screen.getByRole('button', { name: 'Acknowledge' }));

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(apiClient.post).toHaveBeenCalledWith(`/alerts/${open.id}/ack`, { note: 'on my way' });
    expect(toast.success).toHaveBeenCalledWith('Alert acknowledged');
  });

  it('resolving posts to /resolve and says "Alert resolved"', async () => {
    stubApi(apiClient, { [`POST /alerts/${open.id}/resolve`]: { ...open, status: 'resolved' } });
    const { onClose } = renderDialog('resolve');
    expect(screen.getByRole('dialog', { name: 'Resolve alert' })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Resolve' }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(apiClient.post).toHaveBeenCalledWith(`/alerts/${open.id}/resolve`, {});
    expect(toast.success).toHaveBeenCalledWith('Alert resolved');
  });

  it('a blank note is no note at all', async () => {
    stubApi(apiClient, { [`POST /alerts/${open.id}/ack`]: acked });
    renderDialog('acknowledge');
    await userEvent.type(screen.getByLabelText('Note (optional)'), '   ');
    await userEvent.click(screen.getByRole('button', { name: 'Acknowledge' }));
    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    expect(apiClient.post).toHaveBeenCalledWith(`/alerts/${open.id}/ack`, {});
  });

  it('limits the note to what the api accepts', () => {
    renderDialog();
    expect(screen.getByLabelText('Note (optional)')).toHaveAttribute('maxlength', String(NOTE_MAX));
    expect(NOTE_MAX).toBe(1000);
  });

  it('Cancel closes without calling the api', async () => {
    const { onClose } = renderDialog();
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it('Escape closes it', async () => {
    const { onClose } = renderDialog();
    await userEvent.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('explains a 409 and stays open so the operator sees what happened', async () => {
    stubApi(apiClient, {
      [`POST /alerts/${open.id}/ack`]: new ApiError('conflict', {
        status: 409,
        code: 'CONFLICT',
        details: { status: 'acknowledged' },
      }),
      'GET /alerts': { items: [], next_cursor: null },
    });
    const { onClose } = renderDialog('acknowledge');

    await userEvent.click(screen.getByRole('button', { name: 'Acknowledge' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This alert is already acknowledged, so it cannot be acknowledged again. The list has been refreshed.',
    );
    expect(onClose).not.toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Acknowledge' })).toBeEnabled(); // can retry or cancel
  });

  it('starts clean when reopened: no old note, no old error', async () => {
    stubApi(apiClient, {
      [`POST /alerts/${open.id}/ack`]: new ApiError('x', { status: 500 }),
    });
    const closed = <AlertNoteDialog action={null} alert={null} onClose={() => {}} />;
    const shown = <AlertNoteDialog action="acknowledge" alert={open} onClose={() => {}} />;
    const queryClient = makeQueryClient();
    const wrap = (ui) => (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>{ui}</MemoryRouter>
      </QueryClientProvider>
    );
    const view = render(wrap(shown));
    await userEvent.type(screen.getByLabelText('Note (optional)'), 'first try');
    await userEvent.click(screen.getByRole('button', { name: 'Acknowledge' }));
    await screen.findByRole('alert');

    view.rerender(wrap(closed));
    view.rerender(wrap(shown));

    expect(screen.getByLabelText('Note (optional)')).toHaveValue('');
    expect(screen.queryByRole('alert')).toBeNull();
  });
});

describe('focus', () => {
  beforeEach(() => {
    clearTokens();
    vi.mocked(apiClient.post).mockReset();
  });

  function Harness({ onDone }) {
    const [action, setAction] = useState(null);
    return (
      <>
        <button type="button" onClick={() => setAction('acknowledge')}>
          Open dialog
        </button>
        <AlertNoteDialog
          action={action}
          alert={open}
          onClose={() => {
            setAction(null);
            onDone?.();
          }}
        />
      </>
    );
  }

  it('goes back to the button that opened the dialog when it is cancelled or closed with Escape', async () => {
    renderWithProviders(<Harness />);
    const opener = screen.getByRole('button', { name: 'Open dialog' });

    await userEvent.click(opener);
    expect(screen.getByLabelText('Note (optional)')).toHaveFocus(); // moved into the dialog
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(opener).toHaveFocus());

    await userEvent.click(opener);
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(opener).toHaveFocus());
  });

  it('is not stolen back when the opener has gone (the action succeeded and its button went away)', async () => {
    stubApi(apiClient, { [`POST /alerts/${open.id}/ack`]: acked });
    function Vanishing() {
      const [done, setDone] = useState(false);
      const [action, setAction] = useState(null);
      return (
        <>
          {!done && (
            <button type="button" onClick={() => setAction('acknowledge')}>
              Open dialog
            </button>
          )}
          <AlertNoteDialog
            action={action}
            alert={open}
            onClose={() => {
              setDone(true);
              setAction(null);
            }}
          />
        </>
      );
    }
    renderWithProviders(<Vanishing />);
    await userEvent.click(screen.getByRole('button', { name: 'Open dialog' }));
    await userEvent.click(screen.getByRole('button', { name: 'Acknowledge' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(screen.queryByRole('button', { name: 'Open dialog' })).toBeNull();
    expect(document.body).toContainElement(document.activeElement); // focus is somewhere valid, no crash
  });
});

describe('actionErrorMessage', () => {
  const conflict = (details) => new ApiError('c', { status: 409, details });

  it('409 names the status it found, for both actions', () => {
    expect(actionErrorMessage(conflict({ status: 'resolved' }), 'resolve')).toBe(
      'This alert is already resolved, so it cannot be resolved again. The list has been refreshed.',
    );
    expect(actionErrorMessage(conflict({ status: 'resolved' }), 'acknowledge')).toContain(
      'cannot be acknowledged again',
    );
  });

  it('409 without a status still says the alert changed', () => {
    expect(actionErrorMessage(conflict(undefined), 'resolve')).toBe(
      'This alert changed while you were acting on it. The list has been refreshed.',
    );
  });

  it('404, 403 and anything else each say what to do', () => {
    expect(actionErrorMessage(new ApiError('n', { status: 404 }), 'resolve')).toBe(
      'This alert no longer exists. The list has been refreshed.',
    );
    expect(actionErrorMessage(new ApiError('f', { status: 403 }), 'resolve')).toBe(
      'Only operators and admins can act on alerts.',
    );
    expect(actionErrorMessage(new Error('Failed to fetch'), 'acknowledge')).toBe(
      'Could not acknowledge the alert. Check your connection and try again.',
    );
  });

  it('never apologises or shows a raw server message', () => {
    for (const message of [
      actionErrorMessage(new ApiError('Traceback: boom', { status: 500 }), 'resolve'),
      actionErrorMessage(conflict({ status: 'open' }), 'acknowledge'),
    ]) {
      expect(message).not.toMatch(/sorry|oops|traceback/i);
    }
  });
});
