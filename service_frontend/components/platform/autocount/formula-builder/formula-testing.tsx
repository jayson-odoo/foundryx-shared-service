'use client';

/**
 * The formula builder's Testing tab (AC-16-20/21). A mock input `value` in →
 * the transformed output shown LIVE via the client evaluator
 * (`lib/autocount-formula.ts`), never a blank; a "Check on server" button runs
 * the SAME formula through the authoritative backend evaluator so the operator
 * can confirm the client preview matches what the sync will actually do.
 */
import { useMemo, useState } from 'react';
import { CheckCircle2, LoaderCircle, ServerCog, XCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { testFormula } from '@/lib/autocount-formula';
import { cn } from '@/lib/utils';
import type { AutocountFormulaTestResult } from '@/types/autocount';

export interface FormulaTestingProps {
  formula: string;
  /** Server-authoritative single-formula eval (the parity check). */
  onServerTest: (formula: string, value: unknown) => Promise<AutocountFormulaTestResult>;
}

function renderOutput(value: unknown): string {
  if (value === null || value === undefined) return 'null';
  if (typeof value === 'string') return value === '' ? '""' : value;
  return String(value);
}

export function FormulaTesting({ formula, onServerTest }: FormulaTestingProps) {
  const [mockValue, setMockValue] = useState('');
  const [server, setServer] = useState<AutocountFormulaTestResult | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkError, setCheckError] = useState<string | null>(null);

  // Live client evaluation as the operator types (AC-16-20) — never a blank.
  const client = useMemo(() => testFormula(formula, mockValue), [formula, mockValue]);

  // Any edit to the value or formula invalidates a prior server check.
  const staleServer = useMemo(() => {
    if (!server) return null;
    const agrees = server.ok === client.ok && renderOutput(server.output) === renderOutput(client.output);
    return { ...server, agrees };
  }, [server, client]);

  const runServerCheck = async () => {
    setChecking(true);
    setCheckError(null);
    try {
      const res = await onServerTest(formula, mockValue);
      setServer(res);
    } catch {
      setCheckError('The server could not be reached for the parity check.');
      setServer(null);
    } finally {
      setChecking(false);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <label className="flex flex-col gap-1 text-xs font-medium">
        Mock input value
        <Input
          className="font-mono text-sm"
          placeholder="e.g. T"
          value={mockValue}
          onChange={(e) => {
            setMockValue(e.target.value);
            setServer(null);
          }}
        />
      </label>

      <div
        className="flex flex-wrap items-center gap-2 rounded-md bg-muted/40 px-3 py-2 text-sm"
        data-testid="client-output"
      >
        <span className="text-xs font-medium text-muted-foreground">Output</span>
        {client.ok ? (
          <code className="font-medium text-success">{renderOutput(client.output)}</code>
        ) : (
          <span className="flex items-center gap-1.5 font-medium text-destructive">
            <XCircle className="size-3.5" /> {client.error}
          </span>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={runServerCheck}
            disabled={checking || formula.trim() === ''}
          >
            {checking ? (
              <LoaderCircle className="size-4 animate-spin" />
            ) : (
              <ServerCog className="size-4" />
            )}
            Check on server
          </Button>
        </div>

        {checkError && (
          <p className="text-xs text-destructive" data-testid="server-error">
            {checkError}
          </p>
        )}

        {staleServer && (
          <div
            className="flex flex-col gap-1 rounded-md border border-border px-3 py-2 text-sm"
            data-testid="server-output"
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-medium text-muted-foreground">Server</span>
              {staleServer.ok ? (
                <code className="font-medium">{renderOutput(staleServer.output)}</code>
              ) : (
                <span className="font-medium text-destructive">{staleServer.error}</span>
              )}
            </div>
            <span
              className={cn(
                'flex items-center gap-1.5 text-xs',
                staleServer.agrees ? 'text-success' : 'text-destructive',
              )}
            >
              {staleServer.agrees ? (
                <>
                  <CheckCircle2 className="size-3.5" /> Matches the client preview
                </>
              ) : (
                <>
                  <XCircle className="size-3.5" /> Differs from the client preview
                </>
              )}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
