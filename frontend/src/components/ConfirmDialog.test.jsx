import { useState } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ConfirmDialog } from './ConfirmDialog';

const baseProps = {
  title: 'Delete zone',
  description: 'Delete “Gate” from North gate? This can’t be undone.',
  confirmLabel: 'Delete zone',
};

/** What a page does: a button opens it, and the parent decides when it closes. */
function Harness({ onConfirm = () => {}, ...props }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open it
      </button>
      <ConfirmDialog
        {...baseProps}
        {...props}
        open={open}
        onConfirm={() => {
          onConfirm();
          setOpen(false);
        }}
        onClose={() => setOpen(false)}
      />
    </>
  );
}

describe('ConfirmDialog', () => {
  it('shows nothing while closed', () => {
    render(<ConfirmDialog {...baseProps} open={false} onConfirm={() => {}} onClose={() => {}} />);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('asks in words, and names the action on its button', () => {
    render(<ConfirmDialog {...baseProps} open onConfirm={() => {}} onClose={() => {}} />);
    const dialog = screen.getByRole('dialog', { name: 'Delete zone' });
    expect(dialog).toHaveAccessibleDescription(baseProps.description);
    expect(screen.getByRole('button', { name: 'Delete zone' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
  });

  it('confirms only when asked to', async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const onClose = vi.fn();
    render(<ConfirmDialog {...baseProps} open onConfirm={onConfirm} onClose={onClose} />);
    expect(onConfirm).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Delete zone' }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onClose).not.toHaveBeenCalled(); // the parent closes it, after the request
  });

  it('closes on Cancel and on Escape, without confirming', async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const onClose = vi.fn();
    render(<ConfirmDialog {...baseProps} open onConfirm={onConfirm} onClose={onClose} />);
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(2);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('cannot be dismissed or repeated while the request is running', async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const onClose = vi.fn();
    render(<ConfirmDialog {...baseProps} open isPending onConfirm={onConfirm} onClose={onClose} />);
    expect(screen.getByRole('button', { name: 'Working…' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();
    await user.keyboard('{Escape}');
    expect(onClose).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Working…' }));
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('says what went wrong, and stays open', () => {
    render(
      <ConfirmDialog
        {...baseProps}
        open
        error="Only admins can delete zones."
        onConfirm={() => {}}
        onClose={() => {}}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Only admins can delete zones.');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('shows no alert when there is no error', () => {
    render(<ConfirmDialog {...baseProps} open onConfirm={() => {}} onClose={() => {}} />);
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('gives focus back to whatever opened it', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const opener = screen.getByRole('button', { name: 'Open it' });
    await user.click(opener);
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    await user.keyboard('{Escape}');
    await vi.waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(opener).toHaveFocus();
  });

  it('does not try to focus an opener that has gone', async () => {
    const user = userEvent.setup();
    function GoneHarness() {
      const [state, setState] = useState('idle'); // idle | open | gone
      return (
        <>
          {state !== 'gone' && (
            <button type="button" onClick={() => setState('open')}>
              Delete it
            </button>
          )}
          <ConfirmDialog
            {...baseProps}
            open={state === 'open'}
            onConfirm={() => setState('gone')}
            onClose={() => setState('idle')}
          />
        </>
      );
    }
    render(<GoneHarness />);
    await user.click(screen.getByRole('button', { name: 'Delete it' }));
    await user.click(await screen.findByRole('button', { name: 'Delete zone' }));
    await vi.waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(screen.queryByRole('button', { name: 'Delete it' })).toBeNull();
    expect(document.body).toHaveFocus();
  });
});
