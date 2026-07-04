/**
 * Auto-layout for the generic flow canvas (sprint-2/01 "Tidy") — layered
 * left→right via dagre: initial states land on the left, downstream states
 * rank rightward, loop-backs route around. Engine-agnostic on purpose (the
 * Workflow engine reuses it). Pure function — callers persist positions.
 */
import dagre from '@dagrejs/dagre';
import type { Edge, Node } from '@xyflow/react';

export interface AutoLayoutOptions {
  /** Rank direction — left→right reads like a pipeline (default). */
  direction?: 'LR' | 'TB';
  /** Fallbacks when a node hasn't been measured yet. */
  nodeWidth?: number;
  nodeHeight?: number;
}

export function layoutGraph(
  nodes: Node[],
  edges: Edge[],
  { direction = 'LR', nodeWidth = 200, nodeHeight = 90 }: AutoLayoutOptions = {},
): Node[] {
  if (nodes.length === 0) return nodes;

  const graph = new dagre.graphlib.Graph();
  graph.setGraph({ rankdir: direction, nodesep: 60, ranksep: 130, marginx: 40, marginy: 40 });
  graph.setDefaultEdgeLabel(() => ({}));

  for (const node of nodes) {
    graph.setNode(node.id, {
      width: node.measured?.width ?? nodeWidth,
      height: node.measured?.height ?? nodeHeight,
    });
  }
  for (const edge of edges) {
    graph.setEdge(edge.source, edge.target);
  }

  dagre.layout(graph);

  return nodes.map((node) => {
    const placed = graph.node(node.id);
    const width = node.measured?.width ?? nodeWidth;
    const height = node.measured?.height ?? nodeHeight;
    // dagre positions are node centers; React Flow wants the top-left corner.
    return { ...node, position: { x: placed.x - width / 2, y: placed.y - height / 2 } };
  });
}
