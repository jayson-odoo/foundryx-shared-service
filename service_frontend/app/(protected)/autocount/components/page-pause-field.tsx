'use client';

import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

/** Mirrors `http_source/gentle.py` PAGE_PAUSE_FIELD_MIN/MAX + its message. */
export const PAGE_PAUSE_MIN_SECONDS = 0;
export const PAGE_PAUSE_MAX_SECONDS = 90;
const PAGE_PAUSE_INVALID =
  'Pause between pages must be a number from 0 to 90 seconds (max 90 s: longer pauses make the stock run exceed its 2 h limit).';

/** Live mirror of `gentle.clean_page_pause`: blank is fine (the connection's value). */
export function pagePauseError(value: number | null | undefined): string | null {
  if (value === null || value === undefined) return null;
  return Number.isFinite(value) && value >= PAGE_PAUSE_MIN_SECONDS && value <= PAGE_PAUSE_MAX_SECONDS
    ? null
    : PAGE_PAUSE_INVALID;
}

export interface PagePauseFieldProps {
  id: string;
  /** `null` = blank: the connection's "Pause between pages" applies. */
  value: number | null | undefined;
  onChange: (value: number | null) => void;
  disabled?: boolean;
  /** The server's per-field verdict from the last save. */
  error?: string;
  /** "About N pages per run → about X min per run" from this task's last run. */
  hintText?: string | null;
}

/**
 * AUTOCOUNT-LOAD-STRATEGY s6 (owner: "control per entity") - a task's or a
 * document feed's own pause between AutoCount pages / days.
 */
export function PagePauseField({ id, value, onChange, disabled, error, hintText }: PagePauseFieldProps) {
  const shown = error ?? pagePauseError(value);
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>Pause between pages (seconds)</Label>
      <Input
        id={id}
        type="number"
        min={PAGE_PAUSE_MIN_SECONDS}
        max={PAGE_PAUSE_MAX_SECONDS}
        step="any"
        className="w-24"
        value={value === null || value === undefined || Number.isNaN(value) ? '' : value}
        onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
        disabled={disabled}
        aria-invalid={Boolean(shown)}
        data-testid={id}
      />
      {shown ? (
        <p className="text-xs text-destructive" data-testid={`${id}-error`}>
          {shown}
        </p>
      ) : (
        hintText && (
          <p className="text-xs text-muted-foreground" data-testid={`${id}-hint`}>
            {hintText}
          </p>
        )
      )}
    </div>
  );
}
