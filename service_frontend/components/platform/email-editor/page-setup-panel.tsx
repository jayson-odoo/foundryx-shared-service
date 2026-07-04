'use client';

import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { SearchSelect } from '@/components/platform/search-select';
import { DEFAULT_PAGE_SETUP } from '@/lib/template-doc';
import type { PageSetup } from '@/types/templates';

/**
 * Document page-setup panel (F2 D3) — edits `doc.pageSetup` (size / orientation
 * / margins in mm). Only mounted on the document surface.
 */

const SIZE_OPTIONS = [
  { label: 'A4', value: 'A4' },
  { label: 'Letter', value: 'Letter' },
];

const ORIENTATION_OPTIONS = [
  { label: 'Portrait', value: 'portrait' },
  { label: 'Landscape', value: 'landscape' },
];

export interface PageSetupPanelProps {
  value: PageSetup | null;
  onChange: (value: PageSetup) => void;
}

export function PageSetupPanel({ value, onChange }: PageSetupPanelProps) {
  const page: PageSetup = value ?? {
    ...DEFAULT_PAGE_SETUP,
    margins: { ...DEFAULT_PAGE_SETUP.margins },
  };

  const setMargin = (side: keyof PageSetup['margins'], raw: string) => {
    const n = Number(raw);
    if (raw === '' || Number.isNaN(n)) return;
    onChange({ ...page, margins: { ...page.margins, [side]: Math.max(0, n) } });
  };

  return (
    <div data-testid="page-setup-panel" className="flex flex-col gap-3">
      <span className="text-sm font-semibold">Page setup</span>

      <div className="flex flex-col gap-1.5">
        <Label className="text-xs text-muted-foreground">Size</Label>
        <SearchSelect
          options={SIZE_OPTIONS}
          value={page.size}
          onChange={(v) => onChange({ ...page, size: v as PageSetup['size'] })}
          ariaLabel="Page size"
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label className="text-xs text-muted-foreground">Orientation</Label>
        <SearchSelect
          options={ORIENTATION_OPTIONS}
          value={page.orientation}
          onChange={(v) => onChange({ ...page, orientation: v as PageSetup['orientation'] })}
          ariaLabel="Page orientation"
        />
      </div>

      <Separator />
      <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Margins (mm)
      </span>
      <div className="grid grid-cols-2 gap-2">
        {(['top', 'bottom', 'left', 'right'] as const).map((side) => (
          <div key={side} className="flex flex-col gap-1.5">
            <Label className="text-xs capitalize text-muted-foreground">{side}</Label>
            <Input
              type="number"
              min={0}
              aria-label={`Margin ${side}`}
              value={page.margins[side]}
              onChange={(e) => setMargin(side, e.target.value)}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
