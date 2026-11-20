import type { AutocountPullApiKey, AutocountPullSnapshot } from '@/types/autocount';

/**
 * `/autocount/pull`'s N-way segment (AC-10-38) shows two entirely different
 * row shapes under ONE `ResourceList` - a discriminated union keeps a single
 * `ResourceListConfig<T>` type-safe while `use-pull-list-config.tsx` swaps
 * columns/actions per segment at runtime.
 */
export type AutocountPullListRow =
  | ({ kind: 'key' } & AutocountPullApiKey)
  | ({ kind: 'snapshot' } & AutocountPullSnapshot);

export function pullRowId(row: AutocountPullListRow): string {
  return `${row.kind}:${row.id}`;
}
