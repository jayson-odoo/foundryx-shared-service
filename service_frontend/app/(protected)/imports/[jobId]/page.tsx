'use client';

import { use, useEffect, useMemo, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Container } from '@/components/common/container';
import { Card, CardContent, CardHeader, CardHeading, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { Skeleton } from '@/components/ui/skeleton';
import { SearchSelect } from '@/components/platform/search-select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { importService } from '@/services/import-service';
import { registrationService } from '@/services/registration-service';
import { emsService } from '@/services/ems-service';
import { useImportActivity } from '@/providers/import-activity-provider';
import type { ImportConfig, ImportJob, ImportPreview } from '@/types/import';
import type { Offering } from '@/types/registration';
import type { Client } from '@/types/ems';
import { ArrowRight, Download } from 'lucide-react';

const DONT_IMPORT = '__none__';
const IN_FLIGHT = new Set(['pending', 'validating', 'importing']);
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

const PARTICIPANT_ENTITY = 'project_participant';

type TicketMode = 'participants_only' | 'comp' | 'paid';

const TICKET_MODE_OPTIONS: { value: TicketMode; label: string }[] = [
  { value: 'participants_only', label: 'Participants only' },
  { value: 'comp', label: 'Comp (free tickets)' },
  { value: 'paid', label: 'Paid (consolidated invoice)' },
];

/**
 * Import: map · test · import - ONE page (sprint-3/09, redesigned). File headers
 * and system columns sit close together on the left; Test (dry-run) and Import
 * (commit) both run here with results shown inline below - no separate results
 * page. A successful import redirects back to where the upload began; the job is
 * trackable in the Imports drawer.
 */
export default function ImportPage({ params }: { params: Promise<{ jobId: string }> }) {
  const { jobId } = use(params);
  const router = useRouter();
  const searchParams = useSearchParams();
  const from = searchParams.get('from') || '/imports';
  const { refresh } = useImportActivity();

  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [config, setConfig] = useState<ImportConfig | null>(null);
  const [job, setJob] = useState<ImportJob | null>(null);
  const [mapping, setMapping] = useState<Record<string, string | null>>({});
  const [sheet, setSheet] = useState<string | null>(null);
  const [phase, setPhase] = useState<'idle' | 'testing' | 'importing'>('idle');
  const [abortOnInvalid, setAbortOnInvalid] = useState(false);
  const [triggerAutomations, setTriggerAutomations] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Ticket mode (sprint-4/05, R3-5) - only for the project-scoped participant
  // importer. Comp/Paid need a GA offering; Paid needs a bill-to Client.
  const [ticketMode, setTicketMode] = useState<TicketMode>('participants_only');
  const [offeringId, setOfferingId] = useState<string | null>(null);
  const [billToClientId, setBillToClientId] = useState<string | null>(null);
  const [gaOfferings, setGaOfferings] = useState<Offering[]>([]);
  const [clients, setClients] = useState<Client[]>([]);

  const projectId =
    job?.entityType === PARTICIPANT_ENTITY && typeof job.context?.project_id === 'string'
      ? (job.context.project_id as string)
      : null;
  const ticketingEnabled = !!projectId;

  const load = (sheetName?: string) => {
    importService
      .preview(jobId, sheetName)
      .then(async (p) => {
        setPreview(p);
        setSheet(p.sheetName);
        setMapping(p.autoMapping);
        const j = await importService.get(jobId);
        setJob(j);
        setConfig(await importService.getConfig(j.entityType));
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load.'));
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  // Load GA offerings (Comp/Paid picker) + clients (Paid bill-to) lazily.
  useEffect(() => {
    if (!projectId) return;
    registrationService
      .listOfferings(projectId)
      .then((list) => setGaOfferings(list.filter((o) => o.allocationMode === 'GA')))
      .catch(() => setGaOfferings([]));
    emsService
      .clientOptions()
      .then(setClients)
      .catch(() => setClients([]));
  }, [projectId]);

  const offeringOptions = useMemo(
    () => gaOfferings.map((o) => ({ value: o.id, label: o.productName || 'Offering' })),
    [gaOfferings],
  );
  const clientOptions = useMemo(
    () => clients.map((c) => ({ value: c.id, label: c.name })),
    [clients],
  );

  /** Whitelisted ticket-mode context sent to Test + Import (snake_case keys). */
  const ticketContext = (): Record<string, unknown> | undefined => {
    if (!ticketingEnabled) return undefined;
    const ctx: Record<string, unknown> = { ticket_mode: ticketMode };
    if (ticketMode !== 'participants_only') ctx.offering_id = offeringId ?? '';
    if (ticketMode === 'paid') ctx.bill_to_client_id = billToClientId ?? '';
    return ctx;
  };

  const columnOptions = useMemo(
    () =>
      config
        ? [
            { value: DONT_IMPORT, label: "Don't import" },
            ...config.columns.map((c) => ({ value: c.key, label: c.required ? `${c.label} *` : c.label })),
          ]
        : [],
    [config],
  );

  const cleanMapping = () => {
    const clean: Record<string, string | null> = {};
    for (const [h, v] of Object.entries(mapping)) clean[h] = v === DONT_IMPORT ? null : v;
    return clean;
  };

  /** Set mapping → validate → poll until it settles. Returns the settled job. */
  const validate = async (): Promise<ImportJob> => {
    await importService.setMapping(jobId, cleanMapping(), sheet ?? undefined, ticketContext());
    let j = await importService.get(jobId);
    for (let i = 0; i < 30 && IN_FLIGHT.has(j.status); i++) {
      await sleep(600);
      j = await importService.get(jobId);
    }
    setJob(j);
    return j;
  };

  const runTest = async () => {
    setPhase('testing');
    setError(null);
    try {
      await validate();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Test failed.');
    } finally {
      setPhase('idle');
      void refresh();
    }
  };

  const ticketConfigError = (): string | null => {
    if (!ticketingEnabled || ticketMode === 'participants_only') return null;
    if (!offeringId) return 'Pick an offering to issue tickets.';
    if (ticketMode === 'paid' && !billToClientId) return 'Pick a bill-to Client for paid tickets.';
    return null;
  };

  const runImport = async () => {
    const cfgErr = ticketConfigError();
    if (cfgErr) {
      setError(cfgErr);
      return;
    }
    setPhase('importing');
    setError(null);
    try {
      const validated = await validate();
      if (validated.validRows === 0) {
        setError('No valid rows to import. Fix the issues below and test again.');
        return;
      }
      await importService.commit(jobId, {
        abortOnInvalid,
        triggerAutomations,
        context: ticketContext(),
      });
      let j = await importService.get(jobId);
      for (let i = 0; i < 60 && IN_FLIGHT.has(j.status); i++) {
        await sleep(600);
        j = await importService.get(jobId);
      }
      setJob(j);
      void refresh();
      if (j.status === 'done') {
        router.push(from); // back to where the upload began
      } else {
        setError('Import did not complete - see the rows below.');
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Import failed.');
    } finally {
      setPhase('idle');
    }
  };

  const downloadErrors = async () => {
    const blob = await importService.downloadErrorFile(jobId);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'import-errors.csv';
    a.click();
    URL.revokeObjectURL(url);
  };

  if (!preview || !config) {
    return (
      <Container width="fluid">
        <Skeleton className="h-72 w-full" />
      </Container>
    );
  }

  const tested = job && (job.status === 'validated' || job.status === 'done' || job.status === 'failed');
  const errors = job?.errors ?? [];
  const busy = phase !== 'idle';

  return (
    <Container width="fluid">
      <Card>
        <CardHeader>
          <CardHeading>
            <CardTitle>Map columns</CardTitle>
          </CardHeading>
        </CardHeader>
        <CardContent className="space-y-5">
          {/* Mapping - compact, left-aligned (file header ↔ system column). */}
          <div className="max-w-2xl space-y-3">
            {preview.sheets.length > 1 && (
              <div className="max-w-xs space-y-1.5">
                <Label>Sheet</Label>
                <SearchSelect
                  value={sheet}
                  onChange={(v) => {
                    setSheet(v);
                    load(v);
                  }}
                  options={preview.sheets.map((s) => ({ value: s, label: s }))}
                />
              </div>
            )}
            <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-x-3 gap-y-2">
              <span className="text-muted-foreground text-xs font-medium">File column</span>
              <span />
              <span className="text-muted-foreground text-xs font-medium">System column</span>
              {preview.headers.map((header) => (
                <div key={header} className="contents">
                  <div className="truncate text-sm font-medium" title={header}>
                    {header}
                  </div>
                  <ArrowRight className="text-muted-foreground size-4 shrink-0" />
                  <SearchSelect
                    value={mapping[header] ?? DONT_IMPORT}
                    onChange={(v) => setMapping((m) => ({ ...m, [header]: v }))}
                    options={columnOptions}
                  />
                </div>
              ))}
            </div>
          </div>

          {ticketingEnabled && (
            <div className="max-w-2xl space-y-3 rounded-lg border p-4">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label>Ticket mode</Label>
                  <SearchSelect
                    ariaLabel="Ticket mode"
                    value={ticketMode}
                    onChange={(v) => {
                      setTicketMode(v as TicketMode);
                      if (v === 'participants_only') {
                        setOfferingId(null);
                        setBillToClientId(null);
                      }
                      if (v !== 'paid') setBillToClientId(null);
                    }}
                    options={TICKET_MODE_OPTIONS}
                  />
                </div>
                {ticketMode !== 'participants_only' && (
                  <div className="space-y-1.5">
                    <Label>Offering *</Label>
                    <SearchSelect
                      ariaLabel="Offering"
                      value={offeringId}
                      onChange={setOfferingId}
                      options={offeringOptions}
                      placeholder="Select a GA offering"
                      emptyText="No GA offerings for this event"
                    />
                  </div>
                )}
                {ticketMode === 'paid' && (
                  <div className="space-y-1.5">
                    <Label>Bill to (Client) *</Label>
                    <SearchSelect
                      ariaLabel="Bill-to client"
                      value={billToClientId}
                      onChange={setBillToClientId}
                      options={clientOptions}
                      placeholder="Select a client"
                      emptyText="No clients found"
                    />
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="max-w-2xl space-y-2">
            <label className="flex items-center gap-2 text-sm">
              <Checkbox checked={abortOnInvalid} onCheckedChange={(v) => setAbortOnInvalid(!!v)} />
              Abort the whole import if any row is invalid
            </label>
            <label className="flex items-center gap-2 text-sm">
              <Checkbox
                checked={triggerAutomations}
                onCheckedChange={(v) => setTriggerAutomations(!!v)}
              />
              Trigger automations for imported rows
            </label>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" onClick={() => void runTest()} disabled={busy}>
              {phase === 'testing' ? 'Testing…' : 'Test'}
            </Button>
            <Button onClick={() => void runImport()} disabled={busy || !!ticketConfigError()}>
              {phase === 'importing' ? 'Importing…' : 'Import'}
            </Button>
            <Button variant="ghost" onClick={() => router.push(from)} disabled={busy}>
              Cancel
            </Button>
          </div>

          {error && <p className="text-destructive text-sm">{error}</p>}

          {/* Inline results - after Test or a failed Import. */}
          {tested && (
            <div className="space-y-3 border-t pt-5">
              <div className="flex flex-wrap items-center gap-3">
                <Badge variant="success" appearance="light">{job!.validRows} valid</Badge>
                <Badge variant={job!.invalidRows ? 'destructive' : 'secondary'} appearance="light">
                  {job!.invalidRows} invalid
                </Badge>
                <Badge variant="secondary" appearance="light">{job!.totalRows} total</Badge>
                {job!.status === 'failed' && <Badge variant="destructive">failed</Badge>}
              </div>

              {errors.length > 0 && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <p className="text-sm font-medium">Rows needing attention</p>
                    {job!.hasErrorFile && (
                      <Button variant="outline" size="sm" onClick={() => void downloadErrors()}>
                        <Download className="size-3.5" /> Error file (all)
                      </Button>
                    )}
                  </div>
                  {job!.invalidRows > errors.length && (
                    <p className="text-muted-foreground text-xs">
                      Showing first {errors.length} of {job!.invalidRows} - download the error file for all.
                    </p>
                  )}
                  <div className="overflow-x-auto rounded-lg border">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="w-20">Row</TableHead>
                          <TableHead className="w-40">Column</TableHead>
                          <TableHead>Problem</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {errors.map((e, i) => (
                          <TableRow key={i}>
                            <TableCell>{e.row}</TableCell>
                            <TableCell className="font-mono text-xs">{e.column}</TableCell>
                            <TableCell className="text-destructive">{e.message}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                </div>
              )}
              {errors.length === 0 && job!.status === 'validated' && (
                <p className="text-muted-foreground text-sm">
                  All {job!.validRows} rows look good - click Import to bring them in.
                </p>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </Container>
  );
}
