'use client';

import { FileText, History, List, Radar, TriangleAlert } from 'lucide-react';
import { Alert, AlertDescription, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ClampedText } from '@/components/platform/clamped-text';
import { useDatetime } from '@/hooks/use-datetime';
import {
  curatedFields,
  doorLabel,
  formatVendorDateTime,
  formatVendorDay,
  lineColumns,
  vendorValueText,
} from '@/lib/autocount-doc-lookup';
import type {
  DocLookupResult,
  DocLookupStored,
  DocLookupVendorRecord,
} from '@/types/autocount-doc-lookup';
import { LinesGrid, SnapshotsGrid } from './doc-grids';
import { SearchSteps } from './search-steps';

export interface DocResultProps {
  result: DocLookupResult;
  stored: DocLookupStored | null;
  typeLabel: string;
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1 border-b border-border p-3 sm:px-4">
      <span className="text-xs text-muted-foreground">{label}</span>
      <div className="flex min-w-0 flex-wrap items-center gap-1.5 text-sm font-medium">{children}</div>
    </div>
  );
}

function sumOf(lines: DocLookupVendorRecord[], key: string): number | null {
  let total = 0;
  for (const line of lines) {
    const n = Number(line[key]);
    if (!Number.isFinite(n)) return null;
    total += n;
  }
  return total;
}

function money(n: number): string {
  return n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** A found document: re-date warning, current facts, and the four tabs. */
export function DocResult({ result, stored, typeLabel }: DocResultProps) {
  const { formatDateTime } = useDatetime();
  const current = result.current;
  if (!current) return null;
  const snapshots = stored?.snapshots ?? [];
  const ledger = stored?.ledger ?? null;
  const columns = lineColumns(current.lines);
  const subTotal = columns.some((c) => c.key === 'SubTotal') ? sumOf(current.lines, 'SubTotal') : null;
  const headerEntries = Object.entries(current.header);
  const curated = curatedFields(current.header);

  return (
    <div className="flex flex-col gap-4" data-testid="ac-find-result">
      {result.redated && (
        <Alert variant="warning" appearance="light" data-testid="ac-find-redated">
          <AlertIcon>
            <TriangleAlert />
          </AlertIcon>
          <div className="flex flex-col gap-0.5">
            <AlertTitle>
              DocDate changed from {formatVendorDay(result.redated.from)} to {formatVendorDay(result.redated.to)}
            </AlertTitle>
            <AlertDescription>
              Last modified
              {current.lastModifiedBy ? ` by ${current.lastModifiedBy}` : ''} on{' '}
              {formatVendorDateTime(current.lastModified)}. A pull for {formatVendorDay(result.redated.from)} no
              longer returns this document; it is now on {formatVendorDay(result.redated.to)}.
            </AlertDescription>
          </div>
        </Alert>
      )}

      <Card>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-1">
            <h2 className="font-heading text-xl font-semibold" data-testid="ac-find-doc-no">
              {current.docNo}
            </h2>
            <div className="flex flex-wrap items-center gap-1.5 text-sm text-muted-foreground">
              <span>{typeLabel}</span>
              {current.docKey !== null && <span>· DocKey {current.docKey}</span>}
              <span>·</span>
              {current.cancelled ? (
                <Badge variant="destructive" appearance="light" size="sm">
                  Cancelled
                </Badge>
              ) : (
                <Badge variant="success" appearance="light" size="sm">
                  Active
                </Badge>
              )}
              {result.foundBy && (
                <span>
                  · Found by {doorLabel(result.foundBy.door).toLowerCase()} {formatVendorDay(result.foundBy.day)}
                </span>
              )}
            </div>
          </div>

          <div className="grid grid-cols-2 overflow-hidden rounded-md border border-border border-b-0 lg:grid-cols-4">
            <Fact label="DocDate (now)">
              <span data-testid="ac-find-current-date">{formatVendorDay(current.docDate)}</span>
              {result.redated && (
                <span className="font-normal text-muted-foreground line-through">
                  {formatVendorDay(result.redated.from)}
                </span>
              )}
            </Fact>
            <Fact label="Last modified">{formatVendorDateTime(current.lastModified)}</Fact>
            <Fact label="Modified by">{current.lastModifiedBy ?? '-'}</Fact>
            <Fact label="Cancelled">{current.cancelled ? 'Yes' : 'No'}</Fact>
            {curated.map((f) => (
              <Fact key={f.label} label={f.label}>
                <ClampedText text={f.value} lines={1} className="min-w-0" />
              </Fact>
            ))}
            {ledger && (
              <Fact label="Feed">
                <Badge variant="info" appearance="light" size="sm">
                  {ledger.pushedAt ? `Pushed ${formatDateTime(ledger.pushedAt)}` : (ledger.lastOutcome ?? 'Seen')}
                </Badge>
              </Fact>
            )}
          </div>

          <Tabs defaultValue="lines">
            <TabsList variant="line" className="max-w-full overflow-x-auto">
              <TabsTrigger value="lines">
                <List className="size-4" />
                Lines
                <Badge variant="secondary" appearance="light" size="sm">
                  {current.lines.length}
                </Badge>
              </TabsTrigger>
              <TabsTrigger value="snapshots">
                <History className="size-4" />
                Seen in snapshots
                <Badge variant="secondary" appearance="light" size="sm">
                  {snapshots.length}
                </Badge>
              </TabsTrigger>
              <TabsTrigger value="steps">
                <Radar className="size-4" />
                Search steps
              </TabsTrigger>
              <TabsTrigger value="fields">
                <FileText className="size-4" />
                All fields
              </TabsTrigger>
            </TabsList>

            <TabsContent value="lines" className="flex flex-col gap-2 pt-3">
              <LinesGrid lines={current.lines} />
              {subTotal !== null && (
                <div className="flex justify-end gap-3 px-3 text-sm font-semibold" data-testid="ac-find-lines-total">
                  <span>Total</span>
                  <span className="tabular-nums">{money(subTotal)}</span>
                </div>
              )}
            </TabsContent>

            <TabsContent value="snapshots" className="pt-3">
              {snapshots.length === 0 ? (
                <p className="py-6 text-center text-sm text-muted-foreground">Not in any stored snapshot.</p>
              ) : (
                <SnapshotsGrid snapshots={snapshots} currentDocDate={current.docDate} />
              )}
            </TabsContent>

            <TabsContent value="steps" className="pt-3">
              <SearchSteps steps={result.steps} />
            </TabsContent>

            <TabsContent value="fields" className="pt-3">
              <div className="grid grid-cols-[minmax(0,10rem)_minmax(0,1fr)] overflow-hidden rounded-md border border-border text-sm sm:grid-cols-[minmax(0,14rem)_minmax(0,1fr)]">
                {headerEntries.map(([key, value]) => (
                  <div key={key} className="contents">
                    <div className="border-b border-border bg-muted/40 px-3 py-1.5 text-muted-foreground break-words">
                      {key}
                    </div>
                    <div className="border-b border-border px-3 py-1.5 break-words">{vendorValueText(value)}</div>
                  </div>
                ))}
              </div>
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  );
}
