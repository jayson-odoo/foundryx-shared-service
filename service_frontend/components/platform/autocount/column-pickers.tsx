'use client';

import { Badge } from '@/components/ui/badge';
import { Label } from '@/components/ui/label';
import { MultiSelect } from '@/components/platform/multi-select';
import { SearchSelect, type SearchSelectOption } from '@/components/platform/search-select';

/**
 * Read-mode rendering of a column pick (chips, never free text) - shared by
 * the key/watermark/compared pickers below AND the SQL branch's document
 * date-column row (`source-tab.tsx`).
 */
export function ColumnChips({ values, empty }: { values: string[]; empty: string }) {
  if (values.length === 0) {
    return <span className="text-sm text-muted-foreground">{empty}</span>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {values.map((v) => (
        <Badge key={v} variant="secondary" appearance="light" className="font-mono">
          {v}
        </Badge>
      ))}
    </div>
  );
}

export interface ColumnPickersProps {
  editing: boolean;
  /** Every option is enabled; the caller has already excluded/kept legacy
   * values per its own rules (SQL: never a chosen watermark; HTTP: same). */
  keyOptions: SearchSelectOption[];
  /** Includes a `{label:'None', value:''}` leading option when "no
   * watermark" is valid for this entity - omit it when it never is. */
  watermarkOptions: SearchSelectOption[];
  comparedOptions: SearchSelectOption[];
  keyValue: string[];
  onKeyChange: (value: string[]) => void;
  /** `''` = no watermark. */
  watermarkValue: string;
  onWatermarkChange: (value: string) => void;
  comparedValue: string[];
  onComparedChange: (value: string[]) => void;
  /** False until a preview has produced result columns (AC-22-11/AC-08-13). */
  pickersEnabled: boolean;
  fieldErrors?: { keyColumns?: string; watermarkColumn?: string; comparedColumns?: string };
}

/**
 * The key / watermark / compared column pickers (AC-22-09, AC-08-13/19) -
 * dropdowns fed by a preview's result columns, NEVER free text. Shared by
 * the task Source tab's Database branch (SQL: `keyColumns`/`watermarkColumn`/
 * `comparedColumns`) and API branch (open REST API: `keyFields`/
 * `watermarkField`/`comparedFields`) - one component, two callers, per
 * sprint-5/08 D13 ("the SQL tab's pickers extracted into one shared
 * component, dropdowns never free text").
 */
export function ColumnPickers({
  editing,
  keyOptions,
  watermarkOptions,
  comparedOptions,
  keyValue,
  onKeyChange,
  watermarkValue,
  onWatermarkChange,
  comparedValue,
  onComparedChange,
  pickersEnabled,
  fieldErrors = {},
}: ColumnPickersProps) {
  return (
    <div className="grid gap-4 rounded-lg border border-border p-4 md:grid-cols-3">
      <div className="flex min-w-0 flex-col gap-1.5">
        <Label>
          Key columns <span className="text-destructive">*</span>
        </Label>
        {editing ? (
          <MultiSelect
            options={keyOptions}
            value={keyValue}
            onChange={onKeyChange}
            placeholder={pickersEnabled ? 'Pick columns' : 'Test the endpoint first'}
            disabled={!pickersEnabled}
            size="sm"
          />
        ) : (
          <ColumnChips values={keyValue} empty="-" />
        )}
        {fieldErrors.keyColumns && (
          <p className="text-xs text-destructive">{fieldErrors.keyColumns}</p>
        )}
      </div>
      <div className="flex min-w-0 flex-col gap-1.5">
        <Label>Watermark column</Label>
        {editing ? (
          <SearchSelect
            options={watermarkOptions}
            value={watermarkValue}
            onChange={onWatermarkChange}
            placeholder="None"
            disabled={!pickersEnabled}
            ariaLabel="Watermark column"
          />
        ) : (
          <ColumnChips values={watermarkValue ? [watermarkValue] : []} empty="None" />
        )}
        {fieldErrors.watermarkColumn && (
          <p className="text-xs text-destructive">{fieldErrors.watermarkColumn}</p>
        )}
      </div>
      <div className="flex min-w-0 flex-col gap-1.5">
        <Label>Compared columns</Label>
        {editing ? (
          <MultiSelect
            options={comparedOptions}
            value={comparedValue}
            onChange={onComparedChange}
            placeholder={pickersEnabled ? 'All except key columns' : 'Test the endpoint first'}
            disabled={!pickersEnabled}
            size="sm"
          />
        ) : (
          <ColumnChips values={comparedValue} empty="All except key columns" />
        )}
        {fieldErrors.comparedColumns && (
          <p className="text-xs text-destructive">{fieldErrors.comparedColumns}</p>
        )}
      </div>
    </div>
  );
}
