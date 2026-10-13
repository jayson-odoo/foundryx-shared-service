/**
 * Field-level merge choices (plan 20, AC-20-10/16) - pure helpers behind the
 * N-column merge dialog. The server is authoritative (`IdeaMergeService`);
 * `combineMergeValue` mirrors its combine rule only for the dialog's Result
 * preview.
 */
import type { Idea, MergeFieldChoices, MergeFieldKey } from '@/types/ideation';

export type MergeValue = string | string[] | null;

export interface MergeRow {
  key: MergeFieldKey;
  label: string;
  read: (idea: Idea) => MergeValue;
}

const text = (v: string | null | undefined): string | null => {
  const t = (v ?? '').trim();
  return t ? t : null;
};

const list = (v: string[] | null | undefined): string[] | null => {
  const items = (v ?? []).map((s) => s.trim()).filter(Boolean);
  return items.length ? items : null;
};

/** The owner's merge field set, in display order. */
export const MERGE_ROWS: MergeRow[] = [
  { key: 'title', label: 'Title', read: (i) => text(i.title) },
  { key: 'problem', label: 'Business problem', read: (i) => text(i.problem) },
  { key: 'desiredOutcome', label: 'Desired outcome', read: (i) => text(i.desiredOutcome) },
  { key: 'useCases', label: 'Use cases', read: (i) => list(i.useCases) },
  { key: 'currentWorkaround', label: 'Current workaround', read: (i) => text(i.currentWorkaround) },
  { key: 'rawText', label: 'Original message', read: (i) => text(i.rawText) },
];

export const ideaLabel = (idea: Idea): string =>
  idea.ideaNumber ?? text(idea.title) ?? 'another idea';

/** True when at least one column has something to pick in this row. */
export function rowHasContent(row: MergeRow, ideas: Idea[]): boolean {
  return ideas.some((i) => row.read(i) !== null);
}

/** Default ticks: the kept idea's cell, else the first column with content;
 * a row with no content anywhere has no tick. */
export function defaultMergeChoices(ideas: Idea[], keptId: string): MergeFieldChoices {
  const kept = ideas.find((i) => i.id === keptId);
  const choices: MergeFieldChoices = {};
  for (const row of MERGE_ROWS) {
    if (kept && row.read(kept) !== null) {
      choices[row.key] = [kept.id];
      continue;
    }
    const first = ideas.find((i) => row.read(i) !== null);
    choices[row.key] = first ? [first.id] : [];
  }
  return choices;
}

/** Tick / untick one cell, keeping ids in column order. */
export function toggleMergeChoice(
  choices: MergeFieldChoices,
  key: MergeFieldKey,
  ideaId: string,
  columnOrder: string[],
): MergeFieldChoices {
  const current = new Set(choices[key] ?? []);
  if (current.has(ideaId)) current.delete(ideaId);
  else current.add(ideaId);
  return { ...choices, [key]: columnOrder.filter((id) => current.has(id)) };
}

/** Merge is allowed only when every row that has content has a tick. */
export function canSubmitMerge(choices: MergeFieldChoices, ideas: Idea[]): boolean {
  return MERGE_ROWS.every(
    (row) => !rowHasContent(row, ideas) || (choices[row.key] ?? []).length > 0,
  );
}

/** The wire `fields` map - rows without a tick are left out. */
export function mergeFieldsPayload(choices: MergeFieldChoices): MergeFieldChoices {
  const out: MergeFieldChoices = {};
  for (const row of MERGE_ROWS) {
    const ids = choices[row.key] ?? [];
    if (ids.length) out[row.key] = ids;
  }
  return out;
}

/** Mirror of the server combine rule (preview only): one idea = its value;
 * several = text joined with a `--- from IDEA-xxxx ---` line before each value
 * after the first, use cases concatenated without exact duplicates. */
export function combineMergeValue(row: MergeRow, chosen: Idea[]): MergeValue {
  if (row.key === 'useCases') {
    const merged: string[] = [];
    for (const idea of chosen) {
      for (const item of (row.read(idea) as string[] | null) ?? []) {
        if (!merged.includes(item)) merged.push(item);
      }
    }
    return merged.length ? merged : null;
  }
  const parts = chosen
    .map((idea) => ({ idea, value: row.read(idea) as string | null }))
    .filter((p): p is { idea: Idea; value: string } => p.value !== null);
  if (!parts.length) return null;
  const [first, ...rest] = parts;
  return [first.value, ...rest.map((p) => `--- from ${ideaLabel(p.idea)} ---\n${p.value}`)].join(
    '\n\n',
  );
}
