import { describe, expect, it } from 'vitest';
import {
  AVATAR_MAX_BYTES,
  cropRect,
  maxOffset,
  validateAvatarFile,
} from './image-crop';

describe('validateAvatarFile', () => {
  it('accepts png/jpeg/webp under the cap', () => {
    for (const type of ['image/png', 'image/jpeg', 'image/webp']) {
      expect(validateAvatarFile({ type, size: 1024 })).toBeNull();
    }
  });

  it('rejects SVG (XSS surface - plan 06 D5)', () => {
    expect(validateAvatarFile({ type: 'image/svg+xml', size: 10 })).toMatch(
      /unsupported/i,
    );
  });

  it('rejects gif/pdf/unknown', () => {
    expect(validateAvatarFile({ type: 'image/gif', size: 10 })).toMatch(/unsupported/i);
    expect(validateAvatarFile({ type: 'application/pdf', size: 10 })).toMatch(
      /unsupported/i,
    );
  });

  it('rejects files over 2 MB', () => {
    expect(
      validateAvatarFile({ type: 'image/png', size: AVATAR_MAX_BYTES + 1 }),
    ).toMatch(/too large/i);
    expect(validateAvatarFile({ type: 'image/png', size: AVATAR_MAX_BYTES })).toBeNull();
  });
});

describe('cropRect', () => {
  it('zoom 1, no offset = the centered largest square (landscape)', () => {
    expect(cropRect(800, 600, 1, 0, 0)).toEqual({ x: 100, y: 0, size: 600 });
  });

  it('zoom 1, no offset = the centered largest square (portrait)', () => {
    expect(cropRect(600, 800, 1, 0, 0)).toEqual({ x: 0, y: 100, size: 600 });
  });

  it('zoom 2 halves the selection, still centered', () => {
    expect(cropRect(800, 600, 2, 0, 0)).toEqual({ x: 250, y: 150, size: 300 });
  });

  it('offset pans the selection', () => {
    expect(cropRect(800, 600, 2, 100, -50)).toEqual({ x: 350, y: 100, size: 300 });
  });

  it('clamps the selection inside the image', () => {
    // Way past the right edge - selection pins to the edge, never out of bounds.
    const rect = cropRect(800, 600, 2, 10_000, 10_000);
    expect(rect).toEqual({ x: 500, y: 300, size: 300 });
    expect(rect.x + rect.size).toBeLessThanOrEqual(800);
    expect(rect.y + rect.size).toBeLessThanOrEqual(600);
  });

  it('treats zoom < 1 as 1 (never selects beyond the image)', () => {
    expect(cropRect(800, 600, 0.25, 0, 0)).toEqual(cropRect(800, 600, 1, 0, 0));
  });

  it('square image at zoom 1 = the whole image', () => {
    expect(cropRect(512, 512, 1, 0, 0)).toEqual({ x: 0, y: 0, size: 512 });
  });
});

describe('maxOffset', () => {
  it('zoom 1: pan only along the long axis', () => {
    expect(maxOffset(800, 600, 1)).toEqual({ x: 100, y: 0 });
  });

  it('zoom 2: pan in both axes', () => {
    expect(maxOffset(800, 600, 2)).toEqual({ x: 250, y: 150 });
  });

  it('square at zoom 1: no pan at all', () => {
    expect(maxOffset(512, 512, 1)).toEqual({ x: 0, y: 0 });
  });
});
