'use client';

/**
 * Date-format tool (AC-16-14) — a structured sub-panel of the formula builder.
 * The operator picks an INPUT format (how AutoCount sends the date) and an
 * OUTPUT format (what Sorento receives) from a FIXED token vocabulary — never a
 * hand-typed pattern that could drift between the client preview and the server
 * evaluator. A live sample runs a reference date through input→output so the
 * choice is verifiable before it is written into the formula.
 *
 * "Insert" composes `formatDate(parseDate(value, IN), OUT)` and hands it to the
 * builder. The same token set is parsed identically here and in
 * `modules/autocount/formula.py` (this is what makes date parity provable).
 */
import { useEffect, useMemo, useState } from 'react';
import { CalendarClock } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { SearchSelect } from '@/components/platform/search-select';
import {
  DATE_INPUT_FORMATS,
  DATE_OUTPUT_FORMATS,
  ISO_OUTPUT_FORMAT,
  testFormula,
} from '@/lib/autocount-formula';

/** A fixed reference instant, re-rendered into the chosen input format so the
 *  live sample always matches the input the operator just selected. */
const REFERENCE = '2026/03/18 16:03:21';

function sampleFor(inputFormat: string): string {
  const res = testFormula(
    `formatDate(parseDate(value, "yyyy/MM/dd HH:mm:ss"), "${inputFormat}")`,
    REFERENCE,
  );
  return res.ok && typeof res.output === 'string' ? res.output : REFERENCE;
}

/** The formula a given input/output pair writes. Exported for the builder + tests. */
export function dateFormula(inputFormat: string, outputFormat: string): string {
  return `formatDate(parseDate(value, "${inputFormat}"), "${outputFormat}")`;
}

export interface DateFormatToolProps {
  /** Commit the composed `formatDate(parseDate(...))` formula to the builder. */
  onInsert: (formula: string) => void;
  inputFormats?: readonly string[];
  outputFormats?: readonly string[];
}

export function DateFormatTool({
  onInsert,
  inputFormats = DATE_INPUT_FORMATS,
  outputFormats = DATE_OUTPUT_FORMATS,
}: DateFormatToolProps) {
  const [inputFormat, setInputFormat] = useState<string>(inputFormats[0]);
  const [outputFormat, setOutputFormat] = useState<string>(ISO_OUTPUT_FORMAT);
  const [sample, setSample] = useState<string>(() => sampleFor(inputFormats[0]));

  // A new input format resets the sample to one that actually matches it.
  useEffect(() => {
    setSample(sampleFor(inputFormat));
  }, [inputFormat]);

  const formula = useMemo(
    () => dateFormula(inputFormat, outputFormat),
    [inputFormat, outputFormat],
  );
  const preview = useMemo(() => testFormula(formula, sample), [formula, sample]);

  const inputOptions = inputFormats.map((f) => ({ value: f, label: f }));
  const outputOptions = outputFormats.map((f) => ({ value: f, label: f }));

  return (
    <div className="flex flex-col gap-3 rounded-md border border-border p-3">
      <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
        <CalendarClock className="size-4" /> Date format
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-xs font-medium">
          Input format
          <SearchSelect
            options={inputOptions}
            value={inputFormat}
            onChange={setInputFormat}
            ariaLabel="Date input format"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium">
          Output format
          <SearchSelect
            options={outputOptions}
            value={outputFormat}
            onChange={setOutputFormat}
            ariaLabel="Date output format"
          />
        </label>
      </div>

      <div
        className="flex flex-wrap items-center gap-2 rounded-md bg-muted/40 px-3 py-2 text-xs"
        data-testid="date-sample-preview"
      >
        <code className="text-muted-foreground">{sample}</code>
        <span className="text-muted-foreground">→</span>
        {preview.ok ? (
          <code className="font-medium text-success">{String(preview.output)}</code>
        ) : (
          <span className="font-medium text-destructive">{preview.error}</span>
        )}
      </div>

      <div>
        <Button type="button" variant="outline" size="sm" onClick={() => onInsert(formula)}>
          Use this date format
        </Button>
      </div>
    </div>
  );
}
