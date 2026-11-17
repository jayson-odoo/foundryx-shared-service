/**
 * Shrink a large phone screenshot / photo before upload: a JPEG, PNG or WebP over
 * 2 MB is re-encoded (same mime) with its long side capped at 2000 px. Anything
 * else (small images, HEIC, video, audio, PDF) is returned untouched, and so is
 * the original when the browser cannot decode / re-encode it.
 */
const SHRINK_ABOVE_BYTES = 2 * 1024 * 1024;
const MAX_LONG_SIDE = 2000;
const QUALITY = 0.85;
const SHRINKABLE = new Set(['image/jpeg', 'image/png', 'image/webp']);

function toBlob(canvas: HTMLCanvasElement, type: string): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, type, QUALITY));
}

export async function shrinkImage(file: File): Promise<File> {
  if (!SHRINKABLE.has(file.type) || file.size <= SHRINK_ABOVE_BYTES) return file;
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, MAX_LONG_SIDE / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    const ctx = canvas.getContext('2d');
    if (!ctx) {
      bitmap.close();
      return file;
    }
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    const blob = await toBlob(canvas, file.type);
    if (!blob || blob.size === 0 || blob.size >= file.size) return file;
    return new File([blob], file.name, { type: file.type, lastModified: file.lastModified });
  } catch {
    return file;
  }
}
