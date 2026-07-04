'use client';

import { useEffect, useRef, useState } from 'react';
import { LoaderCircleIcon } from 'lucide-react';
import {
  clamp,
  cropImageToBlob,
  cropRect,
  loadImage,
  maxOffset,
} from '@/lib/image-crop';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Slider } from '@/components/ui/slider';

const VIEWPORT = 288; // px — square crop stage
const MAX_ZOOM = 4;

export interface AvatarCropDialogProps {
  /** The picked file (already validated); null closes the dialog. */
  file: File | null;
  onCancel: () => void;
  /** Receives the cropped square blob (≤512px). */
  onCropped: (blob: Blob) => Promise<unknown>;
}

interface Loaded {
  image: HTMLImageElement;
  revoke: () => void;
}

/**
 * Square crop stage (plan 06 D5): drag to pan, slider to zoom, output is
 * downscaled client-side so the bucket never stores multi-MB originals.
 * Hand-rolled (pointer events + canvas) — no image-crop dependency.
 */
export function AvatarCropDialog({ file, onCancel, onCropped }: AvatarCropDialogProps) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [zoom, setZoom] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dragRef = useRef<{ pointerId: number; startX: number; startY: number; baseX: number; baseY: number } | null>(null);

  // (Re)load when the file changes; revoke the object URL on swap/unmount.
  useEffect(() => {
    if (!file) {
      setLoaded(null);
      return;
    }
    let active = true;
    let current: Loaded | null = null;
    setZoom(1);
    setOffset({ x: 0, y: 0 });
    setError(null);
    loadImage(file)
      .then((result) => {
        if (!active) return result.revoke();
        current = result;
        setLoaded(result);
      })
      .catch((e: Error) => active && setError(e.message));
    return () => {
      active = false;
      current?.revoke();
    };
  }, [file]);

  const image = loaded?.image ?? null;
  const natural = image
    ? { w: image.naturalWidth, h: image.naturalHeight }
    : { w: 1, h: 1 };

  // Stage geometry: the SELECTED square always fills the viewport, so the
  // rendered image scale = VIEWPORT / selection size.
  const rect = cropRect(natural.w, natural.h, zoom, offset.x, offset.y);
  const scale = VIEWPORT / rect.size;

  const clampOffsetTo = (zoomValue: number, x: number, y: number) => {
    const limit = maxOffset(natural.w, natural.h, zoomValue);
    return { x: clamp(x, -limit.x, limit.x), y: clamp(y, -limit.y, limit.y) };
  };

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!image) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    dragRef.current = {
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      baseX: offset.x,
      baseY: offset.y,
    };
  };

  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== e.pointerId) return;
    // Pointer px → source px (inverse of the render scale). Dragging the
    // image right moves the selection LEFT, hence the minus.
    const dx = (e.clientX - drag.startX) / scale;
    const dy = (e.clientY - drag.startY) / scale;
    setOffset(clampOffsetTo(zoom, drag.baseX - dx, drag.baseY - dy));
  };

  const onPointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    if (dragRef.current?.pointerId === e.pointerId) dragRef.current = null;
  };

  const onZoom = (value: number) => {
    setZoom(value);
    setOffset((prev) => clampOffsetTo(value, prev.x, prev.y));
  };

  const save = async () => {
    if (!image) return;
    setBusy(true);
    setError(null);
    try {
      const blob = await cropImageToBlob(image, rect);
      await onCropped(blob);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Crop failed.');
      setBusy(false);
      return;
    }
    setBusy(false);
  };

  return (
    <Dialog open={file !== null} onOpenChange={(open) => !open && !busy && onCancel()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Crop avatar</DialogTitle>
          <DialogDescription>
            Drag to reposition, zoom to frame. The square area is what everyone
            sees.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="flex flex-col items-center gap-4">
          <div
            role="application"
            aria-label="Crop area — drag to reposition"
            className="relative touch-none overflow-hidden rounded-md border border-border bg-muted"
            style={{ width: VIEWPORT, height: VIEWPORT }}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
          >
            {image ? (
              // Plain <img> on purpose — object-URL source.
              <img
                src={image.src}
                alt="Crop preview"
                draggable={false}
                className="pointer-events-none absolute max-w-none select-none"
                style={{
                  width: natural.w * scale,
                  height: natural.h * scale,
                  left: -rect.x * scale,
                  top: -rect.y * scale,
                }}
              />
            ) : (
              <div className="flex h-full items-center justify-center">
                <LoaderCircleIcon className="size-5 animate-spin text-muted-foreground" />
              </div>
            )}
            {/* Circle mask preview — purely visual. */}
            <div className="pointer-events-none absolute inset-0 rounded-full border-2 border-white/80 shadow-[0_0_0_9999px_rgba(0,0,0,0.35)]" />
          </div>
          <div className="flex w-full items-center gap-3">
            <span className="text-xs text-muted-foreground">Zoom</span>
            <Slider
              value={[zoom]}
              min={1}
              max={MAX_ZOOM}
              step={0.01}
              onValueChange={([value]) => onZoom(value)}
              disabled={!image || busy}
              aria-label="Zoom"
            />
          </div>
          {error && <p className="text-xs text-destructive">{error}</p>}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void save()} disabled={!image || busy}>
            {busy && <LoaderCircleIcon className="size-3.5 animate-spin" />}
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
