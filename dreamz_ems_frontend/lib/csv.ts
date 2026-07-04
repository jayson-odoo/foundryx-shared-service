/**
 * Shared CSV building (code-review consolidation, extends BL-048e/BL-063h) —
 * one escaping definition for every client-side exporter.
 */
export function csvEscape(cell: string | number | null | undefined): string {
  const text = cell == null ? '' : String(cell);
  return `"${text.replaceAll('"', '""')}"`;
}

export function toCsv(
  header: string[],
  rows: (string | number | null | undefined)[][],
): string {
  return [header, ...rows]
    .map((row) => row.map(csvEscape).join(','))
    .join('\n');
}
