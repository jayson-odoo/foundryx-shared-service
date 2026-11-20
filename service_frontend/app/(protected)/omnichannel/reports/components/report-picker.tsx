'use client';

import { SearchSelect } from '@/components/platform/search-select';
import type { ReportDescriptor, ReportKey } from '@/types/omnichannel';

export interface ReportPickerProps {
  value: ReportKey;
  onChange: (value: ReportKey) => void;
  reports: ReportDescriptor[];
  className?: string;
}

/** Report chooser (plan 30, AC-RPT-44) - a `SearchSelect` over the
 *  `reports/meta` catalog, never a hand-rolled tab strip. */
export function ReportPicker({ value, onChange, reports, className }: ReportPickerProps) {
  return (
    <SearchSelect
      ariaLabel="Report"
      className={className ?? 'w-56'}
      value={value}
      onChange={(v) => onChange(v as ReportKey)}
      options={reports.map((r) => ({ label: r.label, value: r.key }))}
    />
  );
}
