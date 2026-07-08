/**
 * Byte ↔ MB conversions for the omnichannel media-caps settings UI. Caps are
 * stored/transmitted in BYTES (the backend contract) but displayed/edited in MB.
 * Small pure helpers so the conversion is unit-tested in one place.
 */
const BYTES_PER_MB = 1024 * 1024;

/** Bytes → megabytes (raw ratio, unrounded). */
export function bytesToMb(bytes: number): number {
  return bytes / BYTES_PER_MB;
}

/** Megabytes → bytes, rounded to a whole byte. */
export function mbToBytes(mb: number): number {
  return Math.round(mb * BYTES_PER_MB);
}

/**
 * Human MB string for display (ceiling labels, prefilled inputs): at most `dp`
 * decimals with trailing zeros stripped (5 MB → "5", 500 KB → "0.49").
 */
export function formatMb(bytes: number, dp = 2): string {
  return String(parseFloat(bytesToMb(bytes).toFixed(dp)));
}
