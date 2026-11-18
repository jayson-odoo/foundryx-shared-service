import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/** FEEDBACK-ATTACH-IMAGE AC-A-22: `shrinkImage(file): Promise<File>` in lib/shrink-image.ts. */

const MB = 1024 * 1024;
function fileOf(name: string, type: string, size: number): File {
  const f = new File(['x'], name, { type });
  Object.defineProperty(f, 'size', { value: size });
  return f;
}

const SPEC = '@/lib/shrink-image';
const load = () => import(/* @vite-ignore */ SPEC) as Promise<{ shrinkImage: (f: File) => Promise<File> }>;

let drawn: { w: number; h: number; type: string | undefined } | null;

beforeEach(() => {
  drawn = null;
  vi.stubGlobal(
    'createImageBitmap',
    vi.fn().mockResolvedValue({ width: 4000, height: 3000, close: vi.fn() }),
  );
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage: vi.fn() } as never);
  vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(function (
    this: HTMLCanvasElement,
    cb: BlobCallback,
    type?: string,
  ) {
    drawn = { w: this.width, h: this.height, type };
    cb(new Blob(['small'], { type }));
  });
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('shrinkImage (AC-A-22)', () => {
  it.each([
    ['photo.jpg', 'image/jpeg'],
    ['shot.png', 'image/png'],
    ['pic.webp', 'image/webp'],
  ])('re-encodes a >2MB %s to at most 2000px long side, same mime', async (name, type) => {
    const { shrinkImage } = await load();
    const out = await shrinkImage(fileOf(name, type, 5 * MB));
    expect(drawn).not.toBeNull();
    expect(Math.max(drawn!.w, drawn!.h)).toBeLessThanOrEqual(2000);
    expect(drawn!.w / drawn!.h).toBeCloseTo(4 / 3, 1);
    expect(out.type).toBe(type);
    expect(out.name).toBe(name);
    expect(out).not.toBe(undefined);
  });

  it('returns a small image as the same File object', async () => {
    const { shrinkImage } = await load();
    const f = fileOf('small.jpg', 'image/jpeg', 1 * MB);
    expect(await shrinkImage(f)).toBe(f);
    expect(drawn).toBeNull();
  });

  it.each([
    ['p.heic', 'image/heic'],
    ['clip.mp4', 'video/mp4'],
    ['note.ogg', 'audio/ogg'],
    ['spec.pdf', 'application/pdf'],
  ])('sends a big %s unchanged', async (name, type) => {
    const { shrinkImage } = await load();
    const f = fileOf(name, type, 9 * MB);
    expect(await shrinkImage(f)).toBe(f);
    expect(drawn).toBeNull();
  });
});
