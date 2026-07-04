import type { StatusTone } from './status-badge';

/**
 * Engine color handling (sprint-2/01). Statuses store either a legacy color
 * NAME ("green", seeded rows) or a HEX picked in the status drawer. Names map
 * to badge tones; hex renders directly (badge dot / canvas dot inline style).
 */
const COLOR_TONES: Record<string, StatusTone> = {
  green: 'success',
  emerald: 'success',
  teal: 'success',
  lime: 'success',
  amber: 'warning',
  yellow: 'warning',
  orange: 'warning',
  blue: 'info',
  sky: 'info',
  cyan: 'info',
  indigo: 'info',
  violet: 'info',
  purple: 'info',
  red: 'destructive',
  rose: 'destructive',
  pink: 'destructive',
  gray: 'secondary',
  grey: 'secondary',
  slate: 'secondary',
  zinc: 'secondary',
  neutral: 'secondary',
  stone: 'secondary',
  primary: 'primary',
};

export function colorToTone(color: string | null | undefined): StatusTone {
  return COLOR_TONES[(color ?? '').toLowerCase()] ?? 'secondary';
}

export function isHexColor(value: string | null | undefined): boolean {
  return /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(value ?? '');
}

/** Legacy color names → hex (so the picker can display stored names too). */
export const COLOR_NAME_HEX: Record<string, string> = {
  primary: '#FF5A00',
  green: '#22C55E',
  emerald: '#10B981',
  amber: '#F59E0B',
  yellow: '#EAB308',
  orange: '#F97316',
  blue: '#3B82F6',
  cyan: '#06B6D4',
  violet: '#8B5CF6',
  red: '#EF4444',
  gray: '#6B7280',
};

/** Hex for ANY stored color value (name or hex) — display fallback gray. */
export function colorToHex(value: string | null | undefined): string {
  if (isHexColor(value)) return value as string;
  return COLOR_NAME_HEX[(value ?? '').toLowerCase()] ?? '#6B7280';
}

/** Quick-pick swatches from the FoundryX system tokens (brand orange first). */
export const STATUS_COLOR_SWATCHES: { label: string; hex: string }[] = [
  { label: 'Brand', hex: '#FF5A00' },
  { label: 'Green', hex: '#22C55E' },
  { label: 'Amber', hex: '#F59E0B' },
  { label: 'Blue', hex: '#3B82F6' },
  { label: 'Red', hex: '#EF4444' },
  { label: 'Violet', hex: '#8B5CF6' },
  { label: 'Cyan', hex: '#06B6D4' },
  { label: 'Gray', hex: '#6B7280' },
];

