/**
 * Avatar crop helpers (plan sprint-2/06 D5) — pure math here, canvas at the
 * bottom. The crop model: a square viewport over the image; the user pans
 * (offset, in *image* pixels from the centered position) and zooms (scale
 * factor ≥ 1 on top of "cover" fit). The chosen square is downscaled to
 * `AVATAR_OUTPUT_SIZE` client-side so the backend never stores originals.
 */

/** Client-side mirror of the backend caps — server re-validates (sniff-first). */
export const AVATAR_ACCEPT = ['image/png', 'image/jpeg', 'image/webp'];
export const AVATAR_MAX_BYTES = 2 * 1024 * 1024;
export const AVATAR_OUTPUT_SIZE = 512;

/** User-safe validation message, or null when the file is acceptable. */
export function validateAvatarFile(file: Pick<File, 'type' | 'size'>): string | null {
  // NO SVG on purpose — avatars render in many contexts and SVG is an XSS
  // surface (branding's CSP-sandbox lesson, plan 03 review).
  if (!AVATAR_ACCEPT.includes(file.type)) {
    return 'Unsupported file type — use PNG, JPG or WebP.';
  }
  if (file.size > AVATAR_MAX_BYTES) {
    return 'File too large — max 2 MB.';
  }
  return null;
}

export interface CropRect {
  x: number;
  y: number;
  size: number;
}

/**
 * The source-image square selected by (zoom, offset).
 *
 * Definitions:
 * - base selection = the largest centered square that fits the image
 *   ("cover" fit), i.e. `min(width, height)` px.
 * - `zoom` ≥ 1 shrinks the selection (`base / zoom`) — zooming IN.
 * - `offsetX/offsetY` move the selection center, in source pixels; clamped so
 *   the selection never leaves the image.
 */
export function cropRect(
  width: number,
  height: number,
  zoom: number,
  offsetX: number,
  offsetY: number,
): CropRect {
  const safeZoom = Math.max(1, zoom);
  const size = Math.min(width, height) / safeZoom;
  const center = {
    x: width / 2 + offsetX,
    y: height / 2 + offsetY,
  };
  const half = size / 2;
  const x = clamp(center.x - half, 0, width - size);
  const y = clamp(center.y - half, 0, height - size);
  return { x, y, size };
}

/** Largest |offset| (px) the selection center may move at this zoom. */
export function maxOffset(
  width: number,
  height: number,
  zoom: number,
): { x: number; y: number } {
  const size = Math.min(width, height) / Math.max(1, zoom);
  return { x: Math.max(0, (width - size) / 2), y: Math.max(0, (height - size) / 2) };
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

/**
 * Render the selected square to a `size`×`size` blob. WebP (small, universally
 * decodable in 2026 browsers) with a PNG fallback when the canvas refuses.
 */
export function cropImageToBlob(
  image: HTMLImageElement,
  rect: CropRect,
  size: number = AVATAR_OUTPUT_SIZE,
): Promise<Blob> {
  const canvas = document.createElement('canvas');
  // Never upscale tiny sources past their real resolution.
  const out = Math.min(size, Math.round(rect.size)) || 1;
  canvas.width = out;
  canvas.height = out;
  const ctx = canvas.getContext('2d');
  if (!ctx) return Promise.reject(new Error('Canvas unavailable.'));
  ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(image, rect.x, rect.y, rect.size, rect.size, 0, 0, out, out);
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob) return resolve(blob);
        canvas.toBlob(
          (png) => (png ? resolve(png) : reject(new Error('Crop failed.'))),
          'image/png',
        );
      },
      'image/webp',
      0.9,
    );
  });
}

/** Object-URL image loader (caller revokes via the returned `revoke`). */
export function loadImage(file: File): Promise<{ image: HTMLImageElement; revoke: () => void }> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => resolve({ image, revoke: () => URL.revokeObjectURL(url) });
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('Could not read the image.'));
    };
    image.src = url;
  });
}
