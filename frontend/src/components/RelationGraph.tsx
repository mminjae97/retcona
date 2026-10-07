// Force-directed graph of a novel's characters and the relations between them
// (design doc 9.2): characters are nodes, relations are edges labelled with
// their type, with an arrow where a relation points one way. Several relations
// between the same two characters are drawn as separate curves.
import * as d3 from "d3";
import { useEffect, useMemo, useRef, useState } from "react";
import type { RelationPublic } from "../api/relations";

export interface GraphCharacter {
  id: string;
  name: string;
}

interface GraphNode extends d3.SimulationNodeDatum {
  id: string;
  name: string;
}

interface GraphLink extends d3.SimulationLinkDatum<GraphNode> {
  id: string;
  type: string;
  directed: boolean;
  // Which of the relations between this pair it is, and how many there are.
  slot: number;
  of: number;
}

const WIDTH = 720;
const HEIGHT = 520;
const RADIUS = 24;
const CURVE_STEP = 46;

function pairKey(a: string, b: string): string {
  return [a, b].sort().join("|");
}

function endpoints(link: GraphLink) {
  const source = link.source as GraphNode;
  const target = link.target as GraphNode;
  const [sx, sy, tx, ty] = [
    source.x ?? WIDTH / 2,
    source.y ?? HEIGHT / 2,
    target.x ?? WIDTH / 2,
    target.y ?? HEIGHT / 2,
  ];
  const dx = tx - sx;
  const dy = ty - sy;
  const length = Math.hypot(dx, dy) || 1;
  // The bend is measured from one fixed way round the pair, so relations
  // drawn from either of its characters fan out on the same sides.
  const sign = source.id < target.id ? 1 : -1;
  const offset = (link.slot - (link.of - 1) / 2) * CURVE_STEP * sign;
  const cx = (sx + tx) / 2 - (dy / length) * offset;
  const cy = (sy + ty) / 2 + (dx / length) * offset;
  // Stops short of each circle so an arrowhead isn't hidden under it.
  const pull = (x: number, y: number, gap: number) => {
    const d = Math.hypot(cx - x, cy - y) || 1;
    return [x + ((cx - x) / d) * gap, y + ((cy - y) / d) * gap];
  };
  const [x1, y1] = pull(sx, sy, RADIUS);
  const [x2, y2] = pull(tx, ty, RADIUS + 4);
  return {
    path: `M${x1},${y1} Q${cx},${cy} ${x2},${y2}`,
    labelX: (x1 + 2 * cx + x2) / 4,
    labelY: (y1 + 2 * cy + y2) / 4,
  };
}

interface Props {
  characters: GraphCharacter[];
  relations: RelationPublic[];
  selectedRelationId: string | null;
  onSelectRelation: (id: string) => void;
}

export default function RelationGraph({ characters, relations, selectedRelationId, onSelectRelation }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  // Where each character was last drawn, so adding a relation doesn't scatter the graph.
  const positions = useRef(new Map<string, { x: number; y: number }>());
  const [, redraw] = useState(0);

  const { nodes, links } = useMemo(() => {
    const nodes: GraphNode[] = characters.map((character) => ({
      id: character.id,
      name: character.name,
      ...positions.current.get(character.id),
    }));
    const byId = new Map(nodes.map((node) => [node.id, node]));
    const counts = new Map<string, number>();
    const links: GraphLink[] = [];
    for (const relation of relations) {
      const source = byId.get(relation.from_id);
      const target = byId.get(relation.to_id);
      if (!source || !target) continue;
      const pair = pairKey(relation.from_id, relation.to_id);
      const slot = counts.get(pair) ?? 0;
      counts.set(pair, slot + 1);
      links.push({
        id: relation.id,
        source,
        target,
        type: relation.relation_type,
        directed: relation.directed,
        slot,
        of: 0,
      });
    }
    for (const link of links) {
      link.of = counts.get(pairKey((link.source as GraphNode).id, (link.target as GraphNode).id)) ?? 1;
    }
    return { nodes, links };
  }, [characters, relations]);

  useEffect(() => {
    const simulation = d3
      .forceSimulation(nodes)
      .force(
        "link",
        d3
          .forceLink<GraphNode, GraphLink>(links)
          .id((node) => node.id)
          .distance(200),
      )
      .force("charge", d3.forceManyBody().strength(-1400))
      .force("center", d3.forceCenter(WIDTH / 2, HEIGHT / 2))
      .force("collide", d3.forceCollide(RADIUS + 14))
      // Characters that already have a place settle where they are, rather than the whole graph being laid out again.
      .alpha(nodes.every((node) => positions.current.has(node.id)) ? 0.15 : 1)
      .on("tick", () => {
        for (const node of nodes) {
          node.x = Math.max(RADIUS, Math.min(WIDTH - RADIUS, node.x ?? WIDTH / 2));
          node.y = Math.max(RADIUS, Math.min(HEIGHT - RADIUS, node.y ?? HEIGHT / 2));
          positions.current.set(node.id, { x: node.x, y: node.y });
        }
        redraw((count) => count + 1);
      });
    const drag = d3
      .drag<SVGGElement, GraphNode>()
      .on("start", (event, node) => {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        node.fx = node.x;
        node.fy = node.y;
      })
      .on("drag", (event, node) => {
        node.fx = event.x;
        node.fy = event.y;
      })
      .on("end", (event, node) => {
        if (!event.active) simulation.alphaTarget(0);
        node.fx = null;
        node.fy = null;
      });
    if (svgRef.current) {
      d3.select(svgRef.current).selectAll<SVGGElement, GraphNode>("g.graph-node").data(nodes).call(drag);
    }
    return () => {
      simulation.stop();
    };
  }, [nodes, links]);

  return (
    <svg
      ref={svgRef}
      className="relation-graph"
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      role="img"
      aria-label="인물 관계 그래프"
    >
      <defs>
        <marker
          id="relation-arrow"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="8"
          markerHeight="8"
          orient="auto-start-reverse"
        >
          <path d="M0,0 L10,5 L0,10 z" className="graph-arrow" />
        </marker>
      </defs>
      {links.map((link) => {
        const { path, labelX, labelY } = endpoints(link);
        return (
          <g
            key={link.id}
            className={`graph-link${link.id === selectedRelationId ? " selected" : ""}`}
            onClick={() => onSelectRelation(link.id)}
          >
            <path d={path} className="graph-link-hit" />
            <path d={path} className="graph-link-line" markerEnd={link.directed ? "url(#relation-arrow)" : undefined} />
            <text x={labelX} y={labelY} className="graph-link-label">
              {link.type}
            </text>
          </g>
        );
      })}
      {nodes.map((node) => (
        <g key={node.id} className="graph-node" transform={`translate(${node.x ?? WIDTH / 2},${node.y ?? HEIGHT / 2})`}>
          <circle r={RADIUS} />
          <text y={RADIUS + 16}>{node.name}</text>
        </g>
      ))}
    </svg>
  );
}
