// The story timeline graph (design doc 9.3): events are nodes, links are edges.
// Laid out left to right by episode — one column per episode that has events —
// with the events of a column stacked in the order that keeps links short, so
// lines that split and come together again read as branches and merges.
import { useMemo } from "react";
import type { EventPublic, LinkPublic } from "../api/events";
import { LINK_TYPES } from "../api/events";

const NODE_WIDTH = 150;
const NODE_HEIGHT = 66;
const COLUMN_GAP = 110;
const ROW_GAP = 28;
const PAD = 24;

interface Placed {
  event: EventPublic;
  x: number;
  y: number;
}

// What fits in a node's line: Korean text runs about as wide as it is tall.
function clip(text: string, length: number): string {
  return text.length > length ? `${text.slice(0, length - 1)}…` : text;
}

function layout(events: EventPublic[], links: LinkPublic[]) {
  const episodes = [...new Set(events.map((event) => event.episode_index))].sort((a, b) => a - b);
  const rows = new Map<string, number>();
  const placed = new Map<string, Placed>();
  let tallest = 1;
  episodes.forEach((episode, column) => {
    const inColumn = events.filter((event) => event.episode_index === episode);
    // Level with whatever leads to it, once that has a place, so a line runs
    // straight across and not through the events between; otherwise where it
    // came in the list.
    const score = (event: EventPublic, index: number) => {
      const before = links
        .filter((link) => link.to_id === event.id && rows.has(link.from_id))
        .map((link) => rows.get(link.from_id) as number);
      return before.length ? before.reduce((sum, row) => sum + row, 0) / before.length : index;
    };
    let nextFree = 0;
    inColumn
      .map((event, index) => ({ event, score: score(event, index), index }))
      .sort((a, b) => a.score - b.score || a.index - b.index)
      .forEach(({ event, score: wanted }) => {
        const row = Math.max(nextFree, Math.round(wanted));
        nextFree = row + 1;
        rows.set(event.id, row);
        placed.set(event.id, {
          event,
          x: PAD + column * (NODE_WIDTH + COLUMN_GAP),
          y: PAD + row * (NODE_HEIGHT + ROW_GAP),
        });
        tallest = Math.max(tallest, row + 1);
      });
  });
  return {
    placed,
    width: PAD * 2 + Math.max(episodes.length, 1) * NODE_WIDTH + Math.max(episodes.length - 1, 0) * COLUMN_GAP,
    height: PAD * 2 + tallest * NODE_HEIGHT + (tallest - 1) * ROW_GAP,
  };
}

function edge(from: Placed, to: Placed) {
  if (from.x === to.x) {
    // Within one episode: down (or up) the column.
    const down = to.y > from.y;
    const x = from.x + NODE_WIDTH / 2;
    const y1 = down ? from.y + NODE_HEIGHT : from.y;
    const y2 = down ? to.y : to.y + NODE_HEIGHT;
    return { path: `M${x},${y1} L${x},${y2}`, labelX: x, labelY: (y1 + y2) / 2 };
  }
  const forward = to.x > from.x;
  const x1 = forward ? from.x + NODE_WIDTH : from.x;
  const x2 = forward ? to.x : to.x + NODE_WIDTH;
  const y1 = from.y + NODE_HEIGHT / 2;
  const y2 = to.y + NODE_HEIGHT / 2;
  const bend = (x2 - x1) / 2;
  return {
    path: `M${x1},${y1} C${x1 + bend},${y1} ${x2 - bend},${y2} ${x2},${y2}`,
    labelX: (x1 + x2) / 2,
    labelY: (y1 + y2) / 2 - 6,
  };
}

interface Props {
  events: EventPublic[];
  links: LinkPublic[];
  names: Map<string, string>; // character id -> name
  selectedEventId: string | null;
  selectedLinkId: string | null;
  onSelectEvent: (id: string) => void;
  onSelectLink: (id: string) => void;
}

export default function TimelineGraph({
  events,
  links,
  names,
  selectedEventId,
  selectedLinkId,
  onSelectEvent,
  onSelectLink,
}: Props) {
  const { placed, width, height } = useMemo(() => layout(events, links), [events, links]);

  return (
    <div className="timeline-scroll">
      <svg className="timeline-graph" width={width} height={height} role="img" aria-label="스토리 타임라인">
        <defs>
          <marker
            id="timeline-arrow"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="8"
            markerHeight="8"
            orient="auto"
          >
            <path d="M0,0 L10,5 L0,10 z" className="graph-arrow" />
          </marker>
        </defs>
        {links.map((link) => {
          const from = placed.get(link.from_id);
          const to = placed.get(link.to_id);
          if (!from || !to) return null;
          const { path, labelX, labelY } = edge(from, to);
          return (
            <g
              key={link.id}
              className={`timeline-link ${link.link_type}${link.id === selectedLinkId ? " selected" : ""}`}
              onClick={() => onSelectLink(link.id)}
            >
              <path d={path} className="graph-link-hit" />
              <path d={path} className="graph-link-line" markerEnd="url(#timeline-arrow)" />
              {link.link_type !== "sequential" && (
                <text x={labelX} y={labelY} className="graph-link-label">
                  {LINK_TYPES[link.link_type]}
                  {link.branch_reason ? `: ${clip(link.branch_reason, 8)}` : ""}
                </text>
              )}
            </g>
          );
        })}
        {[...placed.values()].map(({ event, x, y }) => {
          const who = event.character_ids.map((id) => names.get(id)).filter((name): name is string => !!name);
          return (
            <g
              key={event.id}
              className={`timeline-event${event.id === selectedEventId ? " selected" : ""}`}
              transform={`translate(${x},${y})`}
              onClick={() => onSelectEvent(event.id)}
            >
              <title>{`${event.episode_index}화\n${event.summary}${who.length ? `\n${who.join(", ")}` : ""}`}</title>
              <rect width={NODE_WIDTH} height={NODE_HEIGHT} rx={8} />
              <text x={10} y={18} className="timeline-event-episode">
                {event.episode_index}화
              </text>
              <text x={10} y={36}>
                {clip(event.summary, 10)}
              </text>
              <text x={10} y={54} className="timeline-event-who">
                {who.length ? clip(who.join(", "), 12) : ""}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
