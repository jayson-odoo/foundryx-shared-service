/**
 * "Tidy" auto-layout (sprint-2/01) - layered LR layout: upstream states left
 * of downstream ones, every node gets a finite position, no two nodes overlap.
 */
import { describe, expect, it } from 'vitest';
import type { Edge, Node } from '@xyflow/react';
import { layoutGraph } from './auto-layout';

const node = (id: string): Node => ({ id, position: { x: 0, y: 0 }, data: {} });
const edge = (source: string, target: string): Edge => ({
  id: `${source}-${target}`,
  source,
  target,
});

describe('layoutGraph', () => {
  it('ranks upstream states left of downstream ones (LR)', () => {
    const nodes = [node('pending'), node('approved'), node('rejected'), node('closed')];
    const edges = [
      edge('pending', 'approved'),
      edge('pending', 'rejected'),
      edge('rejected', 'pending'), // loop-back must not break ranking
      edge('approved', 'closed'),
    ];
    const placed = layoutGraph(nodes, edges);
    const x = Object.fromEntries(placed.map((n) => [n.id, n.position.x]));

    expect(x.pending).toBeLessThan(x.approved);
    expect(x.approved).toBeLessThan(x.closed);
    for (const n of placed) {
      expect(Number.isFinite(n.position.x)).toBe(true);
      expect(Number.isFinite(n.position.y)).toBe(true);
    }
  });

  it('separates same-rank siblings so they never overlap', () => {
    const nodes = [node('a'), node('b'), node('c')];
    const edges = [edge('a', 'b'), edge('a', 'c')]; // b + c share a rank
    const placed = layoutGraph(nodes, edges, { nodeWidth: 200, nodeHeight: 90 });
    const b = placed.find((n) => n.id === 'b')!;
    const c = placed.find((n) => n.id === 'c')!;
    // Same column, vertically separated by at least the node height.
    expect(Math.abs(b.position.y - c.position.y)).toBeGreaterThanOrEqual(90);
  });

  it('returns the input untouched for an empty graph', () => {
    expect(layoutGraph([], [])).toEqual([]);
  });
});
