/**
 * ONE shared duration formatter (plan 30, AC-RPT-48) - every response/
 * resolution duration on the dashboard and reports pages renders through
 * this, so nothing hand-rolls its own seconds->text math. Whole seconds in,
 * a compact two-unit string out: `45s` / `1m 30s` / `3h 30m` / `6d 0h`.
 * `null`/`undefined` (no sample) renders as a plain dash - never `NaN` /
 * "null" text.
 */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return '-';
  const total = Math.max(0, Math.round(seconds));

  if (total < 60) return `${total}s`;

  const minutes = Math.floor(total / 60);
  const remSeconds = total % 60;
  if (minutes < 60) return `${minutes}m ${remSeconds}s`;

  const hours = Math.floor(minutes / 60);
  const remMinutes = minutes % 60;
  if (hours < 24) return `${hours}h ${remMinutes}m`;

  const days = Math.floor(hours / 24);
  const remHours = hours % 24;
  return `${days}d ${remHours}h`;
}
