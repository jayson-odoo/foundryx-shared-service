'use client';

/**
 * Floating offset edge for the generic flow canvas (sprint-2/01).
 *
 * FLOATING: instead of anchoring to the fixed left/right handles, the edge
 * connects the two nodes at the boundary points nearest each other (computed
 * from live node positions) — a back-edge like Suspended→Active exits the
 * side actually FACING Active instead of looping around the canvas (review
 * feedback: "connection from suspended to active is not very visible").
 *
 * OFFSET: a quadratic curve bowed perpendicular by `data.offset` px.
 * Opposite-direction pairs (A→B and B→A) get the same positive offset, which
 * bows them to opposite sides — paths and labels never overlap. The label
 * rides its own curve's midpoint and is clickable (selects the edge).
 */
import type { CSSProperties, MouseEvent } from 'react';
import {
  BaseEdge,
  EdgeLabelRenderer,
  type EdgeProps,
  type InternalNode,
  useInternalNode,
} from '@xyflow/react';
import { cn } from '@/lib/utils';

export interface OffsetEdgeData {
  /** Perpendicular bow in px — 0 = straight. */
  offset?: number;
  onSelect?: (edgeId: string) => void;
  [key: string]: unknown;
}

interface Point {
  x: number;
  y: number;
}

function nodeCenter(node: InternalNode): Point {
  const { x, y } = node.internals.positionAbsolute;
  return {
    x: x + (node.measured.width ?? 0) / 2,
    y: y + (node.measured.height ?? 0) / 2,
  };
}

/** Where the line from this node's center toward `toward` crosses its border. */
function borderPoint(node: InternalNode, toward: Point): Point {
  const center = nodeCenter(node);
  const halfW = (node.measured.width ?? 0) / 2;
  const halfH = (node.measured.height ?? 0) / 2;
  const dx = toward.x - center.x;
  const dy = toward.y - center.y;
  if (dx === 0 && dy === 0) return center;
  const scale = Math.min(
    halfW / Math.max(Math.abs(dx), 1e-6),
    halfH / Math.max(Math.abs(dy), 1e-6),
  );
  return { x: center.x + dx * scale, y: center.y + dy * scale };
}

export function OffsetEdge({
  id,
  source,
  target,
  sourceX,
  sourceY,
  targetX,
  targetY,
  markerEnd,
  style,
  selected,
  label,
  data,
}: EdgeProps) {
  const sourceNode = useInternalNode(source);
  const targetNode = useInternalNode(target);

  const edgeData = (data ?? {}) as OffsetEdgeData;
  const offset = edgeData.offset ?? 0;

  // Float between node borders when both nodes are measured; fall back to
  // the handle coordinates React Flow provides otherwise.
  let from: Point = { x: sourceX, y: sourceY };
  let to: Point = { x: targetX, y: targetY };
  if (sourceNode?.measured.width && targetNode?.measured.width) {
    const sourceCenter = nodeCenter(sourceNode);
    const targetCenter = nodeCenter(targetNode);
    // Bow the control point perpendicular to the center line, then anchor
    // each end where the node border faces the CURVE (not the other center) —
    // arrows leave/enter on the side the eye follows.
    const midX = (sourceCenter.x + targetCenter.x) / 2;
    const midY = (sourceCenter.y + targetCenter.y) / 2;
    const dx = targetCenter.x - sourceCenter.x;
    const dy = targetCenter.y - sourceCenter.y;
    const length = Math.hypot(dx, dy) || 1;
    const control = {
      x: midX + (-dy / length) * offset,
      y: midY + (dx / length) * offset,
    };
    from = borderPoint(sourceNode, offset ? control : targetCenter);
    to = borderPoint(targetNode, offset ? control : sourceCenter);
  }

  const midX = (from.x + to.x) / 2;
  const midY = (from.y + to.y) / 2;
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const length = Math.hypot(dx, dy) || 1;
  const controlX = midX + (-dy / length) * offset;
  const controlY = midY + (dx / length) * offset;
  const path = `M ${from.x} ${from.y} Q ${controlX} ${controlY} ${to.x} ${to.y}`;

  // Quadratic bezier point at t=0.5 — where the label sits ON its curve.
  const labelX = 0.25 * from.x + 0.5 * controlX + 0.25 * to.x;
  const labelY = 0.25 * from.y + 0.5 * controlY + 0.25 * to.y;

  const selectedStyle: CSSProperties = selected
    ? { stroke: 'var(--primary)', strokeWidth: 2 }
    : {};

  const handleLabelClick = (event: MouseEvent) => {
    event.stopPropagation();
    edgeData.onSelect?.(id);
  };

  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} style={{ ...style, ...selectedStyle }} />
      {label != null && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
              pointerEvents: 'all',
            }}
            className={cn(
              'nodrag nopan cursor-pointer rounded-md border bg-background px-1.5 py-0.5 text-[11px] font-medium shadow-xs',
              selected ? 'border-primary text-primary' : 'border-border text-foreground',
            )}
            onClick={handleLabelClick}
          >
            {label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
