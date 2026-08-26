'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { Stage, Layer, Rect, Ellipse, Line, Text as KonvaText, Group, Transformer } from 'react-konva';
import type Konva from 'konva';
import { clampBox, roundForUnit } from '@/lib/canvas-doc';
import type { CanvasDocument, CanvasElement } from '@/types/templates';

/** Geometry quantisation - 1dp in mm (shared with the inspector via roundForUnit). */
const round = (v: number): number => roundForUnit(v, 'mm');

/**
 * The Konva canvas surface (slice 2 D13/D15). Interactive editor ONLY - it never
 * renders the final artifact (the server HTML is authoritative). Select / move /
 * resize / rotate via a Konva Transformer; snap guides to the canvas centre +
 * edges; bleed + safe-area overlay. mm geometry ⇄ px via a fit-to-width scale.
 *
 * QR + storage-backed images render as PLACEHOLDERS here (segno/StorageService
 * are server-side); the Preview tab shows the real server render.
 */

export interface CanvasStageProps {
  doc: CanvasDocument;
  sideIndex: number;
  selectedId: string | null;
  editing: boolean;
  onSelect: (id: string | null) => void;
  /** Commit a geometry change (mm) for one element - pushed through history. */
  onGeometry: (id: string, patch: Partial<CanvasElement>) => void;
}

const SNAP_TOLERANCE_MM = 1.2;

export function CanvasStage({
  doc,
  sideIndex,
  selectedId,
  editing,
  onSelect,
  onGeometry,
}: CanvasStageProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<Konva.Stage>(null);
  const trRef = useRef<Konva.Transformer>(null);
  const [wrapWidth, setWrapWidth] = useState(640);
  const [guides, setGuides] = useState<{ x: number[]; y: number[] }>({ x: [], y: [] });

  const { width: cw, height: ch, bleed } = doc.canvas;
  const side = doc.sides[sideIndex];

  // Fit the canvas (plus bleed margin) to the wrapper width.
  const pxPerMm = useMemo(() => {
    const totalW = cw + bleed * 2;
    return Math.max(1.5, Math.min(8, (wrapWidth - 24) / totalW));
  }, [cw, bleed, wrapWidth]);

  const mm = (v: number) => v * pxPerMm;
  const stageW = mm(cw + bleed * 2);
  const stageH = mm(ch + bleed * 2);
  const off = mm(bleed); // bleed offset so (0,0)mm of the trim sits inside

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w) setWrapWidth(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Attach the transformer to the selected node.
  useEffect(() => {
    const tr = trRef.current;
    const stage = stageRef.current;
    if (!tr || !stage) return;
    const node = selectedId && editing ? stage.findOne(`#${selectedId}`) : null;
    tr.nodes(node ? [node as Konva.Node] : []);
    tr.getLayer()?.batchDraw();
  }, [selectedId, editing, side, pxPerMm]);

  const computeSnap = (node: Konva.Node) => {
    // Snap the node's top-left + centre to the canvas centre/edges (mm space).
    const xMm = (node.x() - off) / pxPerMm;
    const yMm = (node.y() - off) / pxPerMm;
    const w = node.width() * node.scaleX();
    const h = node.height() * node.scaleY();
    const wMm = w / pxPerMm;
    const hMm = h / pxPerMm;
    const lines: { x: number[]; y: number[] } = { x: [], y: [] };
    const targetsX = [0, cw / 2 - wMm / 2, cw - wMm];
    const targetsY = [0, ch / 2 - hMm / 2, ch - hMm];
    let snapX = xMm;
    let snapY = yMm;
    for (const t of targetsX)
      if (Math.abs(xMm - t) < SNAP_TOLERANCE_MM) {
        snapX = t;
        lines.x.push(off + mm(t === 0 ? 0 : t === cw - wMm ? cw : cw / 2));
      }
    for (const t of targetsY)
      if (Math.abs(yMm - t) < SNAP_TOLERANCE_MM) {
        snapY = t;
        lines.y.push(off + mm(t === 0 ? 0 : t === ch - hMm ? ch : ch / 2));
      }
    node.x(off + mm(snapX));
    node.y(off + mm(snapY));
    setGuides(lines);
    return { xMm: snapX, yMm: snapY };
  };

  const renderElement = (el: CanvasElement) => {
    const common = {
      id: el.id,
      name: 'element',
      x: off + mm(el.x),
      y: off + mm(el.y),
      width: mm(el.w),
      height: mm(el.h),
      rotation: el.rotation,
      draggable: editing,
      onMouseDown: () => onSelect(el.id),
      onTap: () => onSelect(el.id),
      // No element may leave the page - clamp the drag to the canvas trim.
      dragBoundFunc: (pos: { x: number; y: number }) => {
        const maxX = off + mm(Math.max(0, cw - el.w));
        const maxY = off + mm(Math.max(0, ch - el.h));
        return {
          x: Math.min(Math.max(pos.x, off), maxX),
          y: Math.min(Math.max(pos.y, off), maxY),
        };
      },
      onDragMove: (e: Konva.KonvaEventObject<DragEvent>) => computeSnap(e.target),
      onDragEnd: (e: Konva.KonvaEventObject<DragEvent>) => {
        const xMm = (e.target.x() - off) / pxPerMm;
        const yMm = (e.target.y() - off) / pxPerMm;
        setGuides({ x: [], y: [] });
        onGeometry(el.id, { x: round(xMm), y: round(yMm) });
      },
      onTransformEnd: (e: Konva.KonvaEventObject<Event>) => {
        const node = e.target;
        const w = Math.max(2, node.width() * node.scaleX());
        const h = Math.max(2, node.height() * node.scaleY());
        node.scaleX(1);
        node.scaleY(1);
        setGuides({ x: [], y: [] });
        // Final containment safety (boundBoxFunc constrains live; this commits).
        const box = clampBox(
          doc.canvas,
          (node.x() - off) / pxPerMm,
          (node.y() - off) / pxPerMm,
          w / pxPerMm,
          h / pxPerMm,
        );
        onGeometry(el.id, { ...box, rotation: round(node.rotation()) });
      },
    } as const;

    if (el.type === 'text') {
      return (
        <KonvaText
          key={el.id}
          {...common}
          text={el.content || 'Text'}
          fontSize={el.fontSize * pxPerMm * 0.353}
          fontFamily={el.fontFamily}
          fontStyle={el.weight >= 700 ? 'bold' : el.weight >= 600 ? '600' : 'normal'}
          align={el.align}
          fill={el.color}
          lineHeight={el.lineHeight}
          wrap="word"
        />
      );
    }
    if (el.type === 'shape') {
      if (el.kind === 'ellipse') {
        return (
          <Ellipse
            key={el.id}
            {...common}
            radiusX={mm(el.w) / 2}
            radiusY={mm(el.h) / 2}
            offsetX={-mm(el.w) / 2}
            offsetY={-mm(el.h) / 2}
            fill={el.fill ?? undefined}
            stroke={el.stroke ?? undefined}
            strokeWidth={el.strokeWidth * pxPerMm}
          />
        );
      }
      if (el.kind === 'line') {
        return (
          <Line
            key={el.id}
            {...common}
            points={[0, 0, mm(el.w), 0]}
            stroke={el.stroke ?? el.fill ?? '#18181B'}
            strokeWidth={Math.max(1, (el.strokeWidth || 0.4) * pxPerMm)}
          />
        );
      }
      return (
        <Rect
          key={el.id}
          {...common}
          fill={el.fill ?? undefined}
          stroke={el.stroke ?? undefined}
          strokeWidth={el.strokeWidth * pxPerMm}
          cornerRadius={el.radius * pxPerMm}
        />
      );
    }
    if (el.type === 'divider') {
      return (
        <Line
          key={el.id}
          {...common}
          points={[0, mm(el.h) / 2, mm(el.w), mm(el.h) / 2]}
          stroke={el.color}
          strokeWidth={Math.max(1, el.thickness * pxPerMm)}
        />
      );
    }
    // image / qr / socialLinks / customHtml / brand placeholders (real render is server-side).
    const PLACEHOLDER: Partial<Record<CanvasElement['type'], string>> = {
      qr: 'QR',
      socialLinks: 'Social',
      customHtml: 'HTML',
      brandHeader: 'Brand header',
      brandFooter: 'Brand footer',
    };
    const label = PLACEHOLDER[el.type] ?? 'Image';
    return (
      <Group key={el.id} {...common}>
        <Rect
          width={mm(el.w)}
          height={mm(el.h)}
          fill="#F4F4F5"
          stroke="#A1A1AA"
          strokeWidth={1}
          dash={[4, 3]}
        />
        <KonvaText
          width={mm(el.w)}
          height={mm(el.h)}
          text={label}
          align="center"
          verticalAlign="middle"
          fontSize={Math.min(mm(el.h) / 3, 14)}
          fill="#71717A"
          listening={false}
        />
      </Group>
    );
  };

  return (
    <div
      ref={wrapRef}
      data-testid="canvas-stage"
      className="w-full overflow-auto rounded-md bg-zinc-200 p-3 dark:bg-zinc-800"
    >
      <Stage
        ref={stageRef}
        width={stageW}
        height={stageH}
        onMouseDown={(e) => {
          if (e.target === e.target.getStage()) onSelect(null);
        }}
        className="mx-auto"
        style={{ background: '#FFFFFF', boxShadow: '0 1px 6px rgba(0,0,0,0.2)' }}
      >
        <Layer>
          {/* trim box (white) */}
          <Rect x={off} y={off} width={mm(cw)} height={mm(ch)} fill="#FFFFFF" listening={false} />
          {side?.elements.map(renderElement)}
          {/* bleed + safe-area guides */}
          {bleed > 0 && (
            <Rect
              x={off}
              y={off}
              width={mm(cw)}
              height={mm(ch)}
              stroke="#F43F5E"
              dash={[6, 4]}
              strokeWidth={1}
              listening={false}
            />
          )}
          {guides.x.map((gx, i) => (
            <Line key={`gx${i}`} points={[gx, 0, gx, stageH]} stroke="#22C55E" strokeWidth={1} listening={false} />
          ))}
          {guides.y.map((gy, i) => (
            <Line key={`gy${i}`} points={[0, gy, stageW, gy]} stroke="#22C55E" strokeWidth={1} listening={false} />
          ))}
          {editing && (
            <Transformer
              ref={trRef}
              rotateEnabled
              keepRatio={false}
              anchorSize={10}
              borderStroke="#FF5A00"
              anchorStroke="#FF5A00"
              boundBoxFunc={(oldBox, newBox) => {
                // Snap the resized box edges to the canvas centre/edges + keep it
                // inside the page (rotated boxes skip snapping - AABB math only).
                if (newBox.rotation) return newBox;
                const tol = mm(SNAP_TOLERANCE_MM);
                let { x, y, width, height } = newBox;
                const xs = [off, off + mm(cw / 2), off + mm(cw)];
                const ys = [off, off + mm(ch / 2), off + mm(ch)];
                const lines: { x: number[]; y: number[] } = { x: [], y: [] };
                for (const e of xs) {
                  if (Math.abs(x - e) < tol) {
                    width += x - e;
                    x = e;
                    lines.x.push(e);
                  } else if (Math.abs(x + width - e) < tol) {
                    width = e - x;
                    lines.x.push(e);
                  }
                }
                for (const e of ys) {
                  if (Math.abs(y - e) < tol) {
                    height += y - e;
                    y = e;
                    lines.y.push(e);
                  } else if (Math.abs(y + height - e) < tol) {
                    height = e - y;
                    lines.y.push(e);
                  }
                }
                // Clamp into the trim.
                const maxX = off + mm(cw);
                const maxY = off + mm(ch);
                if (x < off) {
                  width -= off - x;
                  x = off;
                }
                if (y < off) {
                  height -= off - y;
                  y = off;
                }
                if (x + width > maxX) width = maxX - x;
                if (y + height > maxY) height = maxY - y;
                const minPx = mm(2);
                if (width < minPx) width = minPx;
                if (height < minPx) height = minPx;
                setGuides(lines);
                return { ...newBox, x, y, width, height };
              }}
            />
          )}
        </Layer>
      </Stage>
    </div>
  );
}
