'use client';

/**
 * Inline master-detail (form-in-form) — sprint-4/05. Renders a `<ResourceList>`;
 * clicking a row opens the detail IN PLACE. The consumer renders the detail as an
 * embedded `<ResourceForm>` (same chrome as a page form: icon tabs, FormRow,
 * top-right Back + record-nav + "…" actions) using the `nav` passed in. Reusable:
 * event invoices/tickets, and (later) tickets/invoices under a participant.
 *
 * The list stays mounted (hidden) so its search/filter/scroll survive a drill
 * in/out. Record-nav spans the current page's rows.
 */
import { useMemo, useState, type ReactNode } from 'react';
import { ResourceList } from '@/components/platform/resource-list';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { cn } from '@/lib/utils';

/** Nav + chrome wiring handed to the detail renderer (feed straight into an
 * embedded ResourceForm config: `embedded:true, onBack, inlineNav`). */
export interface DetailNav {
  index: number;
  total: number;
  onPrev: () => void;
  onNext: () => void;
  onBack: () => void;
}

interface Selection<T> {
  rows: T[];
  index: number;
}

export function MasterDetail<T extends object>({
  config,
  detailRender,
}: {
  config: ResourceListConfig<T>;
  detailRender: (row: T, nav: DetailNav) => ReactNode;
}) {
  const [sel, setSel] = useState<Selection<T> | null>(null);

  const listConfig = useMemo<ResourceListConfig<T>>(
    () => ({
      ...config,
      rowHref: () => '#',
      onRowSelect: (_row, index, rows) => setSel({ rows, index }),
    }),
    [config],
  );

  const row = sel ? sel.rows[sel.index] : null;
  const go = (delta: number) =>
    setSel((s) => (s ? { ...s, index: (s.index + delta + s.rows.length) % s.rows.length } : s));

  const nav: DetailNav | null = sel
    ? {
        index: sel.index,
        total: sel.rows.length,
        onPrev: () => go(-1),
        onNext: () => go(1),
        onBack: () => setSel(null),
      }
    : null;

  return (
    <div>
      <div className={cn(sel && 'hidden')}>
        <ResourceList config={listConfig} />
      </div>
      {row && nav && detailRender(row, nav)}
    </div>
  );
}
