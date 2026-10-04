import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import page from '../fixtures/edges_page.json';
import { CameraGraph } from './CameraGraph';

const camera = (n) => ({
  id: `01929e6c-0002-7000-8000-00000000000${n}`,
  code: `cam0${n}`,
  name: `Camera ${n}`,
});
const CAMERAS = [camera(1), camera(2), camera(3)];
const [OVERLAP, ONE_WAY, TWO_WAY] = page.items;

const renderGraph = (props = {}) =>
  render(<CameraGraph cameras={CAMERAS} edges={page.items} {...props} />);

describe('CameraGraph', () => {
  it('draws a node for every camera, labelled with its code', () => {
    renderGraph();
    const nodes = screen.getAllByTestId('camera-node');
    expect(nodes).toHaveLength(3);
    expect(nodes.map((n) => n.textContent)).toEqual(['cam01', 'cam02', 'cam03']);
  });

  it('draws an overlap dashed with no arrow, and its tolerance', () => {
    renderGraph({ edges: [OVERLAP] });
    const link = screen.getByTestId('link-overlap');
    const line = link.querySelector('line');
    expect(line).toHaveAttribute('stroke-dasharray', '6 4');
    expect(line).not.toHaveAttribute('marker-end');
    expect(line).not.toHaveAttribute('marker-start');
    expect(within(link).getByText('±5 s')).toBeInTheDocument();
  });

  it('draws a one-way transit solid with an arrow at the far end only', () => {
    renderGraph({ edges: [ONE_WAY] });
    const line = screen.getByTestId('link-transit').querySelector('line');
    expect(line).not.toHaveAttribute('stroke-dasharray');
    expect(line).toHaveAttribute('marker-end', 'url(#link-arrow)');
    expect(line).not.toHaveAttribute('marker-start');
    expect(screen.getByText('10–45 s')).toBeInTheDocument();
  });

  it('draws a two-way transit with an arrow at both ends', () => {
    renderGraph({ edges: [TWO_WAY] });
    const line = screen.getByTestId('link-transit').querySelector('line');
    expect(line).toHaveAttribute('marker-end', 'url(#link-arrow)');
    expect(line).toHaveAttribute('marker-start', 'url(#link-arrow)');
    expect(screen.getByText('20.5–90 s')).toBeInTheDocument();
  });

  it('stops a line short of the cameras it joins, so an arrow is not hidden under a node', () => {
    renderGraph({ cameras: CAMERAS.slice(0, 2), edges: [OVERLAP] });
    // Two cameras sit at (120, 160) and (360, 160) in the 480 x 320 box, radius 18.
    const line = screen.getByTestId('link-overlap').querySelector('line');
    expect(Number(line.getAttribute('x1'))).toBeCloseTo(120 + 18 + 3);
    expect(Number(line.getAttribute('x2'))).toBeCloseTo(360 - 18 - 3);
    expect(Number(line.getAttribute('y1'))).toBeCloseTo(160);
  });

  it('lights up the selected link and the cameras at its ends, and nothing else', () => {
    renderGraph({ selectedId: ONE_WAY.id });
    const selected = screen
      .getAllByTestId('link-transit')
      .find((link) => link.dataset.selected === 'true');
    expect(screen.getAllByTestId('link-transit')).toHaveLength(2); // only one of them is lit
    expect(selected.querySelector('line')).toHaveClass('stroke-accent');
    expect(selected.querySelector('line')).toHaveAttribute(
      'marker-end',
      'url(#link-arrow-selected)',
    );
    const lit = screen.getAllByTestId('camera-node').filter((n) => n.dataset.selected === 'true');
    expect(lit.map((n) => n.textContent)).toEqual(['cam02', 'cam03']); // ONE_WAY joins cam02 -> cam03
    const unselected = screen.getByTestId('link-overlap');
    expect(unselected.querySelector('line')).toHaveClass('stroke-text-muted');
  });

  it('selects nothing when no id is given', () => {
    renderGraph();
    expect(screen.getAllByTestId('camera-node').every((n) => n.dataset.selected === 'false')).toBe(
      true,
    );
  });

  it('gives two links between the same cameras lanes of their own', () => {
    const second = {
      ...TWO_WAY,
      id: 'another',
      from_camera_id: OVERLAP.from_camera_id,
      to_camera_id: OVERLAP.to_camera_id,
    };
    renderGraph({ edges: [OVERLAP, second] });
    const [a, b] = screen.getAllByTestId(/^link-/).map((g) => g.querySelector('line'));
    expect(a.getAttribute('y1')).not.toBe(b.getAttribute('y1'));
    // Far enough apart for a label (about 12 px tall) on each, so they cannot collide. The lanes are
    // measured square on to the lines: these cameras sit on a slope, so `y` alone would understate it.
    const gap = Math.hypot(
      Number(a.getAttribute('x1')) - Number(b.getAttribute('x1')),
      Number(a.getAttribute('y1')) - Number(b.getAttribute('y1')),
    );
    expect(gap).toBeGreaterThanOrEqual(24);
  });

  it('skips a link to a camera that is no longer configured, rather than failing', () => {
    renderGraph({ cameras: CAMERAS.slice(0, 2), edges: [OVERLAP, ONE_WAY] }); // ONE_WAY needs cam03
    expect(screen.getAllByTestId(/^link-/)).toHaveLength(1);
  });

  it('describes itself in words for a screen reader', () => {
    renderGraph({ edges: [OVERLAP, ONE_WAY] });
    expect(screen.getByRole('img')).toHaveAccessibleName(
      'Camera links diagram: cam01 ↔ cam02, overlap ±5 s; cam02 → cam03, transit 10–45 s.',
    );
  });

  it('says so when there are no links, and still shows the cameras', () => {
    renderGraph({ edges: [] });
    expect(screen.getByRole('img')).toHaveAccessibleName('Camera links diagram: no links yet.');
    expect(screen.getAllByTestId('camera-node')).toHaveLength(3);
  });
});
