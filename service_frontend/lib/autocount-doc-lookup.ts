/**
 * Pure helpers for the AutoCount document finder (sprint-5/17).
 *
 * AutoCount's `DocDate` / `LastModified` are the vendor's OWN wall-clock
 * values (MYT, no zone designator) - never UTC instants. They are shown as
 * written: formatted in UTC so the wall clock passes through unshifted
 * (`parseUtc` pins a zone-less string to UTC). System timestamps (a
 * snapshot's `createdAt`) go through `useDatetime` in the viewer's zone.
 */
import { formatDate, formatDateTime } from '@/lib/datetime';
import type {
  DocLookupDoor,
  DocLookupStep,
  DocLookupVendorRecord,
  DocLookupVendorValue,
} from '@/types/autocount-doc-lookup';

const AS_WRITTEN = { timeZone: 'UTC' } as const;

export function formatVendorDay(day: string | null | undefined): string {
  return formatDate(day, AS_WRITTEN);
}

export function formatVendorDateTime(value: string | null | undefined): string {
  return formatDateTime(value, AS_WRITTEN);
}

export function doorLabel(door: DocLookupDoor): string {
  return door === 'by_last_modified' ? 'Modified on' : 'DocDate';
}

/** Is `day` inside the inclusive ISO-date range? Unknown range = false. */
export function dayInRange(
  day: string | null | undefined,
  from: string | null | undefined,
  to: string | null | undefined,
): boolean {
  if (!day || !from || !to) return false;
  return from <= day && day <= to;
}

export interface DocLookupStepGroup {
  key: string;
  label: string;
  steps: DocLookupStep[];
}

/**
 * Consecutive steps of the same door form one group, in plan order: the
 * hint days (by DocDate, before any by-LastModified step), then
 * "Modified on", then "DocDate".
 */
export function groupSteps(steps: DocLookupStep[]): DocLookupStepGroup[] {
  const groups: DocLookupStepGroup[] = [];
  let seenLastModified = false;
  for (const step of steps) {
    if (step.door === 'by_last_modified') seenLastModified = true;
    const isHint = step.door === 'by_doc_date' && !seenLastModified && groups.length === 0;
    const key = isHint ? 'hint' : step.door;
    const last = groups[groups.length - 1];
    if (last && last.key === key) {
      last.steps.push(step);
      continue;
    }
    const label = key === 'hint' ? 'Known dates' : doorLabel(step.door);
    groups.push({ key, label, steps: [step] });
  }
  return groups;
}

export function stepsDone(steps: DocLookupStep[]): number {
  return steps.filter((s) => s.status === 'hit' || s.status === 'miss' || s.status === 'error').length;
}

/** Plain-text rendering of one vendor value for a table cell. */
export function vendorValueText(value: DocLookupVendorValue | undefined): string {
  if (value === null || value === undefined || value === '') return '-';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

export interface CuratedField {
  label: string;
  value: string;
}

/** The header facts shown above "All fields" - only the ones present. */
export function curatedFields(header: DocLookupVendorRecord): CuratedField[] {
  const out: CuratedField[] = [];
  const has = (key: string) => header[key] !== undefined && header[key] !== null && header[key] !== '';
  if (has('DebtorCode') || has('DebtorName')) {
    out.push({
      label: 'Debtor',
      value: [header.DebtorCode, header.DebtorName].filter((v) => v !== undefined && v !== null && v !== '').join(' · '),
    });
  } else if (has('CreditorCode') || has('CreditorName')) {
    out.push({
      label: 'Creditor',
      value: [header.CreditorCode, header.CreditorName].filter((v) => v !== undefined && v !== null && v !== '').join(' · '),
    });
  }
  if (has('Ref')) out.push({ label: 'Ref', value: vendorValueText(header.Ref) });
  if (has('NetTotal')) {
    const amount = Number(header.NetTotal);
    const text = Number.isFinite(amount)
      ? amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
      : vendorValueText(header.NetTotal);
    out.push({ label: 'Net total', value: has('CurrencyCode') ? `${vendorValueText(header.CurrencyCode)} ${text}` : text });
  }
  return out;
}

/** Line-table columns, in a fixed useful order, only the ones present. */
const LINE_COLUMNS: { key: string; label: string; numeric?: boolean }[] = [
  { key: 'Seq', label: '#', numeric: true },
  { key: 'ItemCode', label: 'Item code' },
  { key: 'Description', label: 'Description' },
  { key: 'Location', label: 'Location' },
  { key: 'UOM', label: 'UOM' },
  { key: 'Qty', label: 'Qty', numeric: true },
  { key: 'UnitPrice', label: 'Unit price', numeric: true },
  { key: 'SubTotal', label: 'Sub total', numeric: true },
];

export function lineColumns(lines: DocLookupVendorRecord[]): { key: string; label: string; numeric?: boolean }[] {
  return LINE_COLUMNS.filter((c) => lines.some((l) => l[c.key] !== undefined));
}
