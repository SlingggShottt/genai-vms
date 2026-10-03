import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import acknowledged from '../fixtures/alert_acknowledged.json';
import open from '../fixtures/alert_open.json';
import { AlertItem } from './AlertItem';

// 10:15:20 IST is 04:45:20 UTC; the alert started at 10:15:20Z = 15:45:20 IST
const now = new Date('2026-10-05T10:17:20Z'); // two minutes after the alert started

function renderItem(alert, props = {}) {
  const onAct = vi.fn();
  render(
    <MemoryRouter>
      <ul>
        <AlertItem alert={alert} now={now} onAct={onAct} {...props} />
      </ul>
    </MemoryRouter>,
  );
  return { onAct, item: screen.getByRole('listitem') };
}

describe('AlertItem', () => {
  it('shows the title, camera, severity (label and shape) and relative + absolute time', () => {
    const { item } = renderItem(open);
    expect(within(item).getByText('Intrusion on cam02')).toBeInTheDocument();
    expect(within(item).getByText('cam02')).toBeInTheDocument();
    expect(within(item).getByText('High')).toBeInTheDocument();
    expect(item.querySelector('svg[data-shape="triangle"]')).not.toBeNull();
    const time = item.querySelector('time');
    expect(time).toHaveAttribute('datetime', open.start_ts);
    expect(time.textContent).toBe('2 min ago, 15:45:20'); // both, never relative alone (§B.8)
  });

  it('has a 3 px bar in the severity colour', () => {
    const { item } = renderItem(open);
    expect(item.className).toContain('border-l-3');
    expect(item.className).toContain('border-sev-high');
    expect(renderItemClass({ ...open, severity: 'critical' })).toContain('border-sev-critical');
  });

  it('an open alert offers Acknowledge, Resolve and Open', () => {
    renderItem(open);
    expect(screen.getByRole('button', { name: 'Acknowledge' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Resolve' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open' })).toHaveAttribute(
      'href',
      `/events/${open.id}`,
    );
  });

  it('an acknowledged alert can be resolved but not acknowledged again, and shows the note', () => {
    renderItem(acknowledged);
    expect(screen.queryByRole('button', { name: 'Acknowledge' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Resolve' })).toBeInTheDocument();
    expect(screen.getByText('Acknowledged: Guard sent to the north gate.')).toBeInTheDocument();
  });

  it('a resolved alert only offers Open', () => {
    renderItem({ ...acknowledged, status: 'resolved' });
    expect(screen.queryByRole('button', { name: 'Acknowledge' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Resolve' })).toBeNull();
    expect(screen.getByRole('link', { name: 'Open' })).toBeInTheDocument();
  });

  it('acknowledged without a note says only "Acknowledged"', () => {
    renderItem({ ...acknowledged, ack_note: null });
    expect(screen.getByText('Acknowledged')).toBeInTheDocument();
  });

  it('reports which action on which alert when a button is pressed', async () => {
    const { onAct } = renderItem(open);
    await userEvent.click(screen.getByRole('button', { name: 'Acknowledge' }));
    await userEvent.click(screen.getByRole('button', { name: 'Resolve' }));
    expect(onAct.mock.calls).toEqual([
      ['acknowledge', open],
      ['resolve', open],
    ]);
  });

  it('says how many other events it is linked with, singular and plural', () => {
    renderItem(open); // group of 2 -> one other
    expect(screen.getByText('Linked with 1 other event on cam03, cam02')).toBeInTheDocument();
  });

  it('pluralises the link text', () => {
    renderItem({ ...open, group: { ...open.group, event_count: 3 } });
    expect(screen.getByText(/Linked with 2 other events on/)).toBeInTheDocument();
  });

  it('shows no link line for an alert alone in its group or with no group', () => {
    renderItem({ ...open, group: { ...open.group, event_count: 1 } });
    expect(screen.queryByText(/Linked with/)).toBeNull();
  });

  it.each([
    ['high', true, 'alert-pulse-high'],
    ['critical', true, 'alert-pulse-critical'],
    ['medium', true, null],
    ['low', true, null],
    ['high', false, null],
  ])('severity %s, new=%s -> pulse class %s', (severity, isNew, expected) => {
    const className = renderItemClass({ ...open, severity }, { isNew });
    if (expected) expect(className).toContain(expected);
    else expect(className).not.toMatch(/alert-pulse/);
  });

  it('marks a new alert for tests and assistive tooling', () => {
    const { item } = renderItem(open, { isNew: true });
    expect(item).toHaveAttribute('data-new', 'true');
  });
});

function renderItemClass(alert, props = {}) {
  const { container, unmount } = render(
    <MemoryRouter>
      <ul>
        <AlertItem alert={alert} now={now} onAct={() => {}} {...props} />
      </ul>
    </MemoryRouter>,
  );
  const className = container.querySelector('li').className;
  unmount();
  return className;
}
