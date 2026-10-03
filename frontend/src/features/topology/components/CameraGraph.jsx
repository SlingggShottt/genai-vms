import { circularLayout, describeGraph, describeTiming, laneOffsets } from '../lib';

const WIDTH = 480;
const HEIGHT = 320;
const NODE_RADIUS = 18;
const GAP = 3; // between a line's end and the camera it points at
const LANE_SPACING = 30; // room for a label (12 px tall) on each line

/** The camera links as a picture: cameras on a circle, a line per link. A dashed line is an
 * overlap (two cameras see the same place at once), a solid line with an arrow is a transit (a
 * trip from one to the other, with an arrowhead at each end if people walk both ways). The label
 * on a line is its timing. The table beside it says all of this in text; `selectedId` lights up
 * the link being edited and the cameras at its ends (cool accent: selection, §B.2).
 */
export function CameraGraph({ cameras, edges, selectedId = null }) {
  const positions = circularLayout(cameras.length);
  const placed = new Map(
    cameras.map((camera, i) => [
      camera.id,
      { camera, x: positions[i].x * WIDTH, y: positions[i].y * HEIGHT },
    ]),
  );
  const labelOf = (id) => placed.get(id)?.camera.code ?? 'unknown camera';
  const drawable = edges.filter((e) => placed.has(e.from_camera_id) && placed.has(e.to_camera_id));
  const lanes = laneOffsets(drawable);
  const selected = drawable.find((edge) => edge.id === selectedId);

  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      role="img"
      aria-label={describeGraph(drawable, labelOf)}
      className="w-full max-w-xl rounded-panel border border-rule bg-surface"
    >
      <defs>
        {[
          ['link-arrow', 'fill-text-muted'],
          ['link-arrow-selected', 'fill-accent'],
        ].map(([id, fill]) => (
          <marker
            key={id}
            id={id}
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="7"
            markerHeight="7"
            orient="auto-start-reverse"
          >
            <path d="M0,0 L10,5 L0,10 z" className={fill} />
          </marker>
        ))}
      </defs>

      {drawable.map((edge) => {
        const from = placed.get(edge.from_camera_id);
        const to = placed.get(edge.to_camera_id);
        const length = Math.hypot(to.x - from.x, to.y - from.y) || 1;
        const [ux, uy] = [(to.x - from.x) / length, (to.y - from.y) / length];
        const lane = (lanes.get(edge.id) ?? 0) * LANE_SPACING;
        const [px, py] = [-uy * lane, ux * lane];
        const start = {
          x: from.x + ux * (NODE_RADIUS + GAP) + px,
          y: from.y + uy * (NODE_RADIUS + GAP) + py,
        };
        const end = {
          x: to.x - ux * (NODE_RADIUS + GAP) + px,
          y: to.y - uy * (NODE_RADIUS + GAP) + py,
        };
        const isSelected = edge.id === selectedId;
        const transit = edge.edge_type === 'transit';
        const arrow = isSelected ? 'url(#link-arrow-selected)' : 'url(#link-arrow)';
        return (
          <g key={edge.id} data-testid={`link-${edge.edge_type}`} data-selected={isSelected}>
            <line
              x1={start.x}
              y1={start.y}
              x2={end.x}
              y2={end.y}
              strokeWidth={isSelected ? 3 : 2}
              strokeDasharray={transit ? undefined : '6 4'}
              markerEnd={transit ? arrow : undefined}
              markerStart={transit && edge.bidirectional ? arrow : undefined}
              className={isSelected ? 'stroke-accent' : 'stroke-text-muted'}
            />
            <text
              x={(start.x + end.x) / 2}
              y={(start.y + end.y) / 2}
              dominantBaseline="central"
              textAnchor="middle"
              className="fill-text font-condensed text-xs"
              stroke="var(--surface)"
              strokeWidth="4"
              paintOrder="stroke"
            >
              {describeTiming(edge)}
            </text>
          </g>
        );
      })}

      {[...placed.values()].map(({ camera, x, y }) => {
        const lit =
          selected &&
          (selected.from_camera_id === camera.id || selected.to_camera_id === camera.id);
        return (
          <g key={camera.id} data-testid="camera-node" data-selected={Boolean(lit)}>
            <circle
              cx={x}
              cy={y}
              r={NODE_RADIUS}
              strokeWidth={lit ? 3 : 2}
              className={
                lit ? 'fill-surface-raised stroke-accent' : 'fill-surface-raised stroke-rule'
              }
            />
            <text
              x={x}
              y={y + NODE_RADIUS + 15}
              textAnchor="middle"
              className="fill-text font-condensed text-sm font-medium"
            >
              {camera.code}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
