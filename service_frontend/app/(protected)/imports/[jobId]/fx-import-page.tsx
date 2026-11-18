'use client';

/**
 * The import page under the Foundryx UIUX switch (slice W3-JOBS): steps 2 to 4
 * of the import wizard, one stage under the other on the page.
 *
 * - Match the columns: each file column, an arrow, its searchable system
 *   column; required ones marked.
 * - Check: the dry run ("Test" today). It shows "10 rows ready · 2 with
 *   problems", the problem rows and their file, and the choice between
 *   skipping the rows with problems and stopping if any row has one (today's
 *   "Abort the whole import if any row is invalid").
 * - Import: the red action names the count ("Import 10 users").
 *
 * Approved workflow change (owner, "Check always before Import"): the red
 * action is Check until the current columns, sheet and ticket choices have
 * been checked; only then does it become Import. Changing any of them sends
 * it back to Check. Every request is today's: Check sends exactly what Test
 * sends, Import exactly what Import sends (it re-validates, then commits), and
 * the page goes back to where the upload began when the import is done.
 */
import { use, useEffect, useMemo, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { ArrowRight } from 'lucide-react';
import { Container } from '@/components/common/container';
import { PageHeader } from '@/components/platform/page-header';
import { SearchSelect } from '@/components/platform/search-select';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { FxFileIcon } from '@/components/fx/icons';
import {
  useRegisterMainAction,
  type FxMainActionSpec,
} from '@/components/fx/actions/page-actions-context';
import { FxImportSteps } from '@/components/platform/import-wizard/fx-import-steps';
import { MODE_LABELS } from '@/components/platform/import-wizard/import-modal';
import { FxJobChip } from '@/components/platform/jobs-drawer/fx-job-chip';
import { fmtCount, importItem } from '@/components/platform/jobs-drawer/fx-job-items';
import { cn } from '@/lib/utils';
import { importService } from '@/services/import-service';
import { registrationService } from '@/services/registration-service';
import { emsService } from '@/services/ems-service';
import { useImportActivity } from '@/providers/import-activity-provider';
import type { ImportConfig, ImportJob, ImportPreview } from '@/types/import';
import type { Offering } from '@/types/registration';
import type { Client } from '@/types/ems';
import { ImportErrorsTable } from './import-errors-table';

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

/** What a check covers: a change to any of these needs a new check. */
export function checkSignature(
  mapping: Record<string, string | null>,
  sheet: string | null,
  context: Record<string, unknown> | undefined,
): string {
  return JSON.stringify({ mapping, sheet, context: context ?? null });
}

/** The red action for where the import is (pure, tested). */
export function importMainAction(input: {
  checked: boolean;
  job: ImportJob | null;
  noun: string;
  phase: 'idle' | 'testing' | 'importing';
  ticketError: string | null;
  onCheck: () => void;
  onImport: () => void;
}): FxMainActionSpec | null {
  const { checked, job, noun, phase, ticketError } = input;
  if (job?.status === 'done') return null;
  if (!checked || phase === 'testing') {
    return {
      id: 'check',
      label: phase === 'testing' ? 'Checking…' : 'Check rows',
      fullLabel: `Check the ${noun} in this file without importing them`,
      onClick: input.onCheck,
      working: phase === 'testing',
    };
  }
  const ready = job?.validRows ?? 0;
  const label = `Import ${fmtCount(ready)} ${noun}`;
  return {
    id: 'import',
    label: phase === 'importing' ? 'Importing…' : label,
    fullLabel: label,
    onClick: input.onImport,
    working: phase === 'importing',
    blocked: ticketError
      ? { reason: ticketError, pulseTarget: 'import-tickets' }
      : ready === 0
        ? { reason: 'No rows are ready to import.', pulseTarget: 'import-columns' }
        : undefined,
  };
}

export function FxImportPage({ params }: { params: Promise<{ jobId: string }> }) {
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
  /** The inputs the last finished check ran with. */
  const [checkedSig, setCheckedSig] = useState<string | null>(null);

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

  // Same reads as today, in the same order.
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

  /** Set mapping → validate → poll until it settles (today's `validate`). */
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

  const signature = checkSignature(mapping, sheet, ticketContext());
  const checked = checkedSig !== null && checkedSig === signature;

  /** Check = today's Test, request for request. */
  const runCheck = async () => {
    const sig = signature;
    setPhase('testing');
    setError(null);
    try {
      await validate();
      setCheckedSig(sig);
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

  /** Import = today's Import, request for request. */
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

  const noun = (config?.label ?? job?.entityType ?? 'rows').toLowerCase();
  const ticketError = ticketConfigError();
  const main = useMemo(
    () =>
      preview && config
        ? importMainAction({
            checked,
            job,
            noun,
            phase,
            ticketError,
            onCheck: () => void runCheck(),
            onImport: () => void runImport(),
          })
        : null,
    // The handlers read the latest state through the closure of this render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [preview, config, checked, job, noun, phase, ticketError, signature, abortOnInvalid, triggerAutomations],
  );
  useRegisterMainAction(main);

  if (!preview || !config) {
    return (
      <Container width="fluid">
        {error ? (
          <p role="alert" className="py-16 text-center text-sm text-destructive">
            {error}
          </p>
        ) : (
          <Skeleton className="h-72 w-full" />
        )}
      </Container>
    );
  }

  const done = job?.status === 'done';
  const step = done ? 3 : checked ? 3 : 1;
  const errors = job?.errors ?? [];
  const showResults =
    !!job && (checked || done || job.status === 'failed') && job.totalRows > 0;
  const required = config.columns.filter((c) => c.required);
  const mapped = new Set(Object.values(mapping));
  const unmatched = required.filter((c) => !mapped.has(c.key));
  const chip = job ? importItem(job) : null;

  return (
    <Container width="fluid">
      <PageHeader
        title={`Import ${config.label}`}
        description={
          chip ? (
            <span className="flex items-center gap-2">
              <FxJobChip label={chip.status} tone={chip.tone} />
              <span>{MODE_LABELS[job!.mode]}</span>
            </span>
          ) : undefined
        }
        actions={
          <Button variant="fx-quiet" onClick={() => router.push(from)} disabled={phase !== 'idle'}>
            {done ? 'Back' : 'Cancel'}
          </Button>
        }
      />

      <div className="mx-auto flex w-full max-w-3xl flex-col gap-5 pb-10">
        <section className="rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface) p-4 sm:p-5">
          <FxImportSteps current={step} allDone={done} />
        </section>

        {/* Step 2: match the columns. */}
        <section
          aria-labelledby="fx-import-match"
          data-fx-pulse-target="import-columns"
          className="flex flex-col gap-4 rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface) p-4 sm:p-5"
        >
          <h2 id="fx-import-match" className="text-base font-semibold text-(--fx-ink)">
            Match the columns
          </h2>
          {preview.sheets.length > 1 && (
            <div className="flex max-w-xs flex-col gap-1.5">
              <Label>Sheet</Label>
              <SearchSelect
                ariaLabel="Sheet"
                value={sheet}
                onChange={(v) => {
                  setSheet(v);
                  load(v);
                }}
                options={preview.sheets.map((s) => ({ value: s, label: s }))}
              />
            </div>
          )}
          <div className="hidden grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] gap-x-3 text-xs font-semibold text-(--fx-ink-3) sm:grid">
            <span>File column</span>
            <span className="w-4" />
            <span>System column</span>
          </div>
          <ul className="flex flex-col gap-3 sm:gap-2">
            {preview.headers.map((header) => {
              const value = mapping[header] ?? DONT_IMPORT;
              return (
                <li
                  key={header}
                  className="grid grid-cols-1 items-center gap-1.5 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] sm:gap-x-3"
                >
                  <span className="truncate text-sm font-semibold text-(--fx-ink)" title={header}>
                    {header}
                  </span>
                  <ArrowRight aria-hidden="true" className="hidden size-4 shrink-0 text-(--fx-ink-3) sm:block" />
                  <SearchSelect
                    ariaLabel={`System column for ${header}`}
                    value={value}
                    onChange={(v) => setMapping((m) => ({ ...m, [header]: v }))}
                    options={columnOptions}
                    className={cn(value === DONT_IMPORT && 'text-(--fx-ink-3)')}
                  />
                </li>
              );
            })}
          </ul>
          {unmatched.length > 0 && (
            <p className="text-sm text-(--fx-warn-ink)">
              No column for {unmatched.map((c) => c.label).join(', ')}
            </p>
          )}

          {ticketingEnabled && (
            <div
              data-fx-pulse-target="import-tickets"
              className="grid grid-cols-1 gap-3 rounded-(--fx-r-m) border border-(--fx-line) p-4 sm:grid-cols-2"
            >
              <div className="flex flex-col gap-1.5">
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
                <div className="flex flex-col gap-1.5">
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
                <div className="flex flex-col gap-1.5">
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
          )}
        </section>

        {/* Step 3: the check (a test run that changes nothing). */}
        <section
          aria-labelledby="fx-import-check"
          className="flex flex-col gap-4 rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface) p-4 sm:p-5"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 id="fx-import-check" className="text-base font-semibold text-(--fx-ink)">
              Check
            </h2>
            {checked && !done && (
              <Button
                variant="fx-text"
                size="sm"
                onClick={() => void runCheck()}
                disabled={phase !== 'idle'}
              >
                Check again
              </Button>
            )}
          </div>

          {showResults && job ? (
            <>
              <p className="text-sm text-(--fx-ink) tabular-nums">
                <span className="font-semibold">{fmtCount(job.validRows)} rows ready</span>
                {' · '}
                <span className={job.invalidRows ? 'font-semibold text-(--fx-warn-ink)' : ''}>
                  {fmtCount(job.invalidRows)} with problems
                </span>
                <span className="text-(--fx-ink-3)"> · {fmtCount(job.totalRows)} in the file</span>
              </p>
              {errors.length > 0 && (
                <div className="flex flex-col gap-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-sm font-semibold text-(--fx-ink)">Rows with problems</p>
                    {job.hasErrorFile && (
                      <Button variant="fx-text" size="sm" onClick={() => void downloadErrors()}>
                        <FxFileIcon type="CSV" arrow="down" size={16} /> Download rows with problems
                      </Button>
                    )}
                  </div>
                  {job.invalidRows > errors.length && (
                    <p className="text-xs text-(--fx-ink-3)">
                      First {fmtCount(errors.length)} of {fmtCount(job.invalidRows)}
                    </p>
                  )}
                  <ImportErrorsTable errors={errors} />
                </div>
              )}
            </>
          ) : (
            !done && (
              <p className="text-sm text-(--fx-ink-3)">
                {phase === 'testing' ? 'Checking the rows…' : 'Not checked yet'}
              </p>
            )
          )}

          {!done && (
            <div className="flex flex-col gap-3 border-t border-(--fx-line) pt-4">
              <div
                role="radiogroup"
                aria-label="Rows with problems"
                className="inline-flex w-fit flex-wrap gap-1 rounded-(--fx-r-pill) border border-(--fx-line-2) p-0.5"
              >
                {[
                  { value: false, label: 'Skip rows with problems' },
                  { value: true, label: 'Stop if any row has a problem' },
                ].map((opt) => (
                  <Button
                    key={opt.label}
                    type="button"
                    role="radio"
                    aria-checked={abortOnInvalid === opt.value}
                    variant="ghost"
                    size="sm"
                    onClick={() => setAbortOnInvalid(opt.value)}
                    className={cn(
                      'h-8 rounded-(--fx-r-pill) px-3 text-(--fx-ink-2)',
                      abortOnInvalid === opt.value &&
                        'bg-(--fx-link-bg) font-semibold text-(--fx-link) hover:bg-(--fx-link-bg) hover:text-(--fx-link)',
                    )}
                  >
                    {opt.label}
                  </Button>
                ))}
              </div>
              <label className="flex items-center gap-2 text-sm text-(--fx-ink)">
                <Checkbox
                  checked={triggerAutomations}
                  onCheckedChange={(v) => setTriggerAutomations(!!v)}
                />
                Trigger automations for imported rows
              </label>
            </div>
          )}

          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
        </section>

        {done && job && chip && (
          <section className="flex flex-col gap-1 rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface) p-4 sm:p-5">
            <h2 className="text-base font-semibold text-(--fx-ink)">Import</h2>
            <p className="text-sm text-(--fx-ink) tabular-nums">{chip.detail}</p>
          </section>
        )}
      </div>
    </Container>
  );
}
