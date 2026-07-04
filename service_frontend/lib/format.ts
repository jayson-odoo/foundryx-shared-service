/** Shared display formatters. Locale-stable, null-safe.
 *
 * Datetime formatting moved to `lib/datetime.ts` + `hooks/use-datetime.ts`
 * (plan sprint-2/05) — timestamps render in the user's timezone there; never
 * re-add tz-blind date formatters here. */

/** Initials from a name ("Durbex Verifier" -> "DV"); falls back to "?" */
export function initials(name: string | null | undefined): string {
  if (!name) return '?';
  const parts = name.trim().split(/\s+/).slice(0, 2);
  return parts.map((p) => p[0]?.toUpperCase() ?? '').join('') || '?';
}
