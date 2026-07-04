'use client';

/**
 * Signature draw pad (plan sprint-3/01, spike c) — a pointer-driven canvas the
 * user draws into; the answer is the canvas exported as a PNG data-URL string.
 * Works with touch AND mouse (Pointer Events, `touch-none` so the gesture
 * doesn't scroll the page) and at 375px (the canvas backing store tracks the
 * element's measured width × devicePixelRatio so strokes stay crisp on hi-DPI).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export interface SignaturePadProps {
  /** PNG data-URL of an existing signature (rehydrate), or '' for blank. */
  value: string;
  onChange: (dataUrl: string) => void;
  disabled?: boolean;
  ariaLabel?: string;
  invalid?: boolean;
}

const PAD_HEIGHT = 160;
const STROKE_WIDTH = 2;

export function SignaturePad({ value, onChange, disabled, ariaLabel, invalid }: SignaturePadProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const drawing = useRef(false);
  const last = useRef<{ x: number; y: number } | null>(null);
  const [hasInk, setHasInk] = useState(Boolean(value));

  // Size the backing store to the measured CSS box × DPR, then restore any
  // existing value. Re-runs on container resize (responsive — 375px ↔ desktop).
  const sizeCanvas = useCallback(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    const dpr = window.devicePixelRatio || 1;
    const cssWidth = wrap.clientWidth || 300;
    canvas.width = Math.round(cssWidth * dpr);
    canvas.height = Math.round(PAD_HEIGHT * dpr);
    canvas.style.width = `${cssWidth}px`;
    canvas.style.height = `${PAD_HEIGHT}px`;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.lineWidth = STROKE_WIDTH;
    ctx.strokeStyle = '#111827';
    if (value) {
      const img = new Image();
      img.onload = () => ctx.drawImage(img, 0, 0, cssWidth, PAD_HEIGHT);
      img.src = value;
    }
  }, [value]);

  useEffect(() => {
    sizeCanvas();
    const wrap = wrapRef.current;
    if (!wrap || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => sizeCanvas());
    ro.observe(wrap);
    return () => ro.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- value handled inside sizeCanvas
  }, []);

  const pointFor = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  };

  const start = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (disabled) return;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    drawing.current = true;
    last.current = pointFor(e);
  };

  const move = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!drawing.current || disabled) return;
    const ctx = canvasRef.current?.getContext('2d');
    if (!ctx || !last.current) return;
    const point = pointFor(e);
    ctx.beginPath();
    ctx.moveTo(last.current.x, last.current.y);
    ctx.lineTo(point.x, point.y);
    ctx.stroke();
    last.current = point;
    setHasInk(true);
  };

  const end = () => {
    if (!drawing.current) return;
    drawing.current = false;
    last.current = null;
    const canvas = canvasRef.current;
    if (canvas) onChange(canvas.toDataURL('image/png'));
  };

  const clear = () => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (canvas && ctx) {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
    setHasInk(false);
    onChange('');
  };

  return (
    <div className="space-y-2">
      <div
        ref={wrapRef}
        className={cn(
          'w-full overflow-hidden rounded-md border bg-background',
          invalid ? 'border-destructive/60' : 'border-input',
          disabled && 'opacity-60',
        )}
      >
        <canvas
          ref={canvasRef}
          role="img"
          aria-label={ariaLabel ?? 'Signature'}
          className="block w-full touch-none"
          style={{ height: PAD_HEIGHT }}
          onPointerDown={start}
          onPointerMove={move}
          onPointerUp={end}
          onPointerLeave={end}
        />
      </div>
      {!disabled && (
        <Button type="button" variant="outline" size="sm" onClick={clear} disabled={!hasInk}>
          Clear
        </Button>
      )}
    </div>
  );
}
