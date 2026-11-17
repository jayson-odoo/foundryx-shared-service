import { describe, expect, it } from 'vitest';
import { boardBrandStyle, boardBrandTitle } from './board-brand';

/** Lane SS-MULTI-PRODUCT-BOARD (AC-MPB-7): a product's board colour drives the
 * board's primary colour family; no colour = the default look. */
describe('boardBrandStyle', () => {
  it('maps one colour to the primary family with derived shades', () => {
    const s = boardBrandStyle({ name: 'Sorento CRM', color: '#3b82f6' }) as Record<string, string>;
    expect(s['--primary']).toBe('#3b82f6');
    expect(s['--primary-transparent']).toBe('rgba(59, 130, 246, 0.2)');
    expect(s['--primary-active']).toContain('#3b82f6');
    expect(s['--primary-soft']).toContain('#3b82f6');
    // White reads on a mid blue.
    expect(s['--primary-foreground']).toBe('#ffffff');
  });

  it('picks a dark foreground on a light colour', () => {
    const s = boardBrandStyle({ name: null, color: '#fde047' }) as Record<string, string>;
    expect(s['--primary-foreground']).toBe('#0a0a0a');
  });

  it('no brand, or a name without a colour, keeps the default colours', () => {
    expect(boardBrandStyle(null)).toBeUndefined();
    expect(boardBrandStyle({ name: 'EcoHub', color: null })).toBeUndefined();
    expect(boardBrandStyle({ name: null, color: 'blue' })).toBeUndefined();
  });
});

describe('boardBrandTitle', () => {
  it('reads "<name> feedback", null without a name', () => {
    expect(boardBrandTitle({ name: 'Sorento CRM', color: '#3b82f6' })).toBe('Sorento CRM feedback');
    expect(boardBrandTitle({ name: null, color: '#3b82f6' })).toBeNull();
    expect(boardBrandTitle(null)).toBeNull();
  });
});
