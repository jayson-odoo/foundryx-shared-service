'use client';

import { useEffect, useState } from 'react';
import { LoaderCircleIcon, TriangleAlert } from 'lucide-react';
import { Alert, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { SearchSelect } from '@/components/platform/search-select';
import type {
  DocFeedContractGate,
  DocFeedEligibleConnection,
  DocFeedKey,
  DocFeedMode,
  DocFeedSchedule,
  DocFeedUpdateInput,
  DocFeedWindow,
} from '@/types/autocount';
import { ApiError } from '@/lib/api-client';
import {
  DEFAULT_DOC_FEED_SCHEDULE,
  DEFAULT_DOC_FEED_WINDOW,
  DOC_FEED_POLL_BASIS_OPTIONS,
  DOC_FEED_POLL_HAS_WATERMARK,
  docFeedWindowErrors,
  readFieldErrors,
} from '@/lib/autocount-etl';
import { docFeedGateWarning, docFeedLabel } from '../../components/autocount-meta';
import {
  ScheduleCadenceCards,
  scheduleCadenceErrors,
} from '../../components/schedule-cadence-cards';

const MODE_SEGMENT_CLASS =
  'data-[state=on]:bg-primary data-[state=on]:text-primary-foreground data-[state=on]:border-primary';

export interface DocFeedConfigDialogProps {
  feed: DocFeedKey;
  current: {
    connectionId: string | null;
    mode: DocFeedMode;
    contractGate: DocFeedContractGate | null;
    /** Omitted = the default cadence (poll 60 min, sweep every 24 h). */
    schedule?: DocFeedSchedule;
    /** Omitted = the default read window (LastModified, 1 day, 45-day re-check). */
    window?: DocFeedWindow;
    nextPollAt?: string | null;
    nextSweepAt?: string | null;
  };
  eligibleConnections: DocFeedEligibleConnection[];
  onClose: () => void;
  /** Rejects on a failed save; a 422's `fieldErrors` land on the cards. */
  onSave: (input: DocFeedUpdateInput) => Promise<void>;
}

/**
 * Configure a document feed's connection + mode (AC-14-91). Mode is a
 * `ToggleGroup`, not a `SearchSelect` (the codebase's own documented
 * exception - "fixed 2-3-option micro-enums may stay plain Select" - the
 * SAME shape the Schedule tab's Push/Pull toggle already uses): Dry run and
 * Push are not merely disabled when unreachable, they are ABSENT
 * (foolproof-UI, AC-14-91) - until a connection is chosen and the consumer
 * contract gate is open, Off is the only offered value.
 *
 * sprint-5/19 (AC-19-11) - the feed's schedule is edited with the SAME
 * cadence cards the Entities task editor's Schedule tab uses (poll =
 * incremental, deletion sweep = reconcile); Save is held while any is invalid.
 *
 * DOC-FEED-WINDOW - the read window rides inside the SAME two cards: the
 * Poll card gains the vendor door (LastModified | DocDate) + lookback days,
 * the reconcile card (now "Re-check": content re-push + deletions) its
 * DocDate window in days.
 */
export function DocFeedConfigDialog({
  feed,
  current,
  eligibleConnections,
  onClose,
  onSave,
}: DocFeedConfigDialogProps) {
  const [connectionId, setConnectionId] = useState<string | null>(current.connectionId);
  const [mode, setMode] = useState<DocFeedMode>(current.mode);
  const stored = current.schedule ?? DEFAULT_DOC_FEED_SCHEDULE;
  const [schedule, setSchedule] = useState<DocFeedSchedule>(stored);
  const storedWindow = current.window ?? DEFAULT_DOC_FEED_WINDOW;
  const [readWindow, setReadWindow] = useState<DocFeedWindow>(storedWindow);
  const [saving, setSaving] = useState(false);
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    setConnectionId(current.connectionId);
    setMode(current.mode);
  }, [feed, current.connectionId, current.mode]);

  useEffect(() => {
    setSchedule({
      incrementalMinutes: stored.incrementalMinutes,
      reconcileMode: stored.reconcileMode,
      reconcileHours: stored.reconcileHours,
      reconcileAt: stored.reconcileAt,
    });
  }, [
    feed,
    stored.incrementalMinutes,
    stored.reconcileMode,
    stored.reconcileHours,
    stored.reconcileAt,
  ]);

  useEffect(() => {
    setReadWindow({
      pollBasis: storedWindow.pollBasis,
      pollLookbackDays: storedWindow.pollLookbackDays,
      recheckDays: storedWindow.recheckDays,
    });
  }, [feed, storedWindow.pollBasis, storedWindow.pollLookbackDays, storedWindow.recheckDays]);

  const windowClientErrors = docFeedWindowErrors(readWindow);
  const windowError = (key: keyof DocFeedWindow): string | undefined =>
    serverErrors[key] ?? windowClientErrors[key];
  const scheduleInvalid =
    Object.keys(scheduleCadenceErrors(schedule, DOC_FEED_POLL_HAS_WATERMARK)).length > 0 ||
    Object.keys(windowClientErrors).length > 0;

  function patchWindow(patch: Partial<DocFeedWindow>) {
    setServerErrors({});
    setReadWindow((prev) => ({ ...prev, ...patch }));
  }

  function daysValue(raw: string): number {
    return raw === '' ? NaN : Number(raw);
  }
  const armed = current.mode !== 'off';

  const gate = current.contractGate;
  const canArm = Boolean(connectionId) && gate === null;

  // A stored mode the current selection can no longer reach (connection
  // cleared, or the gate shut since it was last saved) falls back to Off
  // rather than keep an unreachable choice visibly selected.
  useEffect(() => {
    if (!canArm && mode !== 'off') setMode('off');
  }, [canArm, mode]);

  async function submit() {
    setSaving(true);
    try {
      setServerErrors({});
      await onSave({ connectionId, mode, schedule, window: readWindow });
    } catch (error) {
      // The caller already toasted it; keep the dialog open with the
      // server's per-field verdict next to the field (Entities parity).
      setServerErrors(error instanceof ApiError ? readFieldErrors(error.detail) : {});
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Configure - {docFeedLabel(feed)}</DialogTitle>
          <DialogDescription className="sr-only">Configure {docFeedLabel(feed)}</DialogDescription>
        </DialogHeader>
        <DialogBody>
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label>Connection</Label>
              <SearchSelect
                ariaLabel="Connection"
                placeholder="Choose a connection"
                value={connectionId}
                onChange={setConnectionId}
                options={eligibleConnections.map((c) => ({
                  value: c.id,
                  label: `${c.name} - ${c.book}`,
                }))}
                emptyText="No eligible connections."
              />
            </div>
            {gate && connectionId && (
              <Alert variant="warning" appearance="light" data-testid="doc-feed-gate-warning">
                <AlertIcon>
                  <TriangleAlert />
                </AlertIcon>
                <AlertTitle>{docFeedGateWarning(gate)}</AlertTitle>
              </Alert>
            )}
            <div className="flex flex-col gap-2">
              <Label>Mode</Label>
              <ToggleGroup
                type="single"
                size="sm"
                variant="outline"
                value={mode}
                onValueChange={(value) => {
                  if (value === 'off' || value === 'dry_run' || value === 'push') setMode(value);
                }}
                aria-label="Mode"
              >
                <ToggleGroupItem value="off" className={MODE_SEGMENT_CLASS} data-testid="doc-feed-mode-off">
                  Off
                </ToggleGroupItem>
                {canArm && (
                  <ToggleGroupItem value="dry_run" className={MODE_SEGMENT_CLASS} data-testid="doc-feed-mode-dry-run">
                    Dry run
                  </ToggleGroupItem>
                )}
                {canArm && (
                  <ToggleGroupItem value="push" className={MODE_SEGMENT_CLASS} data-testid="doc-feed-mode-push">
                    Push
                  </ToggleGroupItem>
                )}
              </ToggleGroup>
            </div>
            <ScheduleCadenceCards
              editing
              value={schedule}
              onChange={(patch) => {
                setServerErrors({});
                setSchedule((prev) => ({ ...prev, ...patch }));
              }}
              hasWatermark={DOC_FEED_POLL_HAS_WATERMARK}
              fieldErrors={serverErrors}
              nextIncrementalAt={armed ? (current.nextPollAt ?? null) : null}
              nextReconcileAt={armed ? (current.nextSweepAt ?? null) : null}
              incrementalTitle="Poll"
              reconcileTitle="Re-check"
              idPrefix="doc-feed-schedule"
              className="grid gap-4 sm:grid-cols-2"
              incrementalExtra={
                <>
                  <div className="flex flex-col gap-1.5">
                    <Label>Read by</Label>
                    <ToggleGroup
                      type="single"
                      size="sm"
                      variant="outline"
                      value={readWindow.pollBasis}
                      onValueChange={(value) => {
                        if (value === 'last_modified' || value === 'doc_date') {
                          patchWindow({ pollBasis: value });
                        }
                      }}
                      aria-label="Read by"
                    >
                      {DOC_FEED_POLL_BASIS_OPTIONS.map((option) => (
                        <ToggleGroupItem
                          key={option.value}
                          value={option.value}
                          className={MODE_SEGMENT_CLASS}
                          data-testid={`doc-feed-window-basis-${option.value}`}
                        >
                          {option.label}
                        </ToggleGroupItem>
                      ))}
                    </ToggleGroup>
                  </div>
                  <WindowDaysField
                    id="doc-feed-window-lookback-days"
                    label="Look back"
                    min={0}
                    max={30}
                    value={readWindow.pollLookbackDays}
                    error={windowError('pollLookbackDays')}
                    onChange={(raw) => patchWindow({ pollLookbackDays: daysValue(raw) })}
                  />
                </>
              }
              reconcileExtra={
                <WindowDaysField
                  id="doc-feed-window-recheck-days"
                  label="Window"
                  min={1}
                  max={180}
                  value={readWindow.recheckDays}
                  error={windowError('recheckDays')}
                  onChange={(raw) => patchWindow({ recheckDays: daysValue(raw) })}
                />
              }
            />
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button
            onClick={submit}
            disabled={saving || scheduleInvalid}
            data-testid="doc-feed-config-save"
          >
            {saving && <LoaderCircleIcon className="size-4 animate-spin" />}
            Save feed
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface WindowDaysFieldProps {
  id: string;
  label: string;
  min: number;
  max: number;
  value: number;
  error?: string;
  onChange: (raw: string) => void;
}

/** One "N days" input of the read window - the cadence cards' own
 * number-input + unit + inline error shape. */
function WindowDaysField({ id, label, min, max, value, error, onChange }: WindowDaysFieldProps) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <div className="flex items-center gap-2">
        <Input
          id={id}
          type="number"
          min={min}
          max={max}
          step={1}
          className="w-24"
          value={Number.isFinite(value) ? value : ''}
          onChange={(e) => onChange(e.target.value)}
          aria-invalid={Boolean(error)}
          data-testid={id}
        />
        <span className="text-sm text-muted-foreground">days</span>
      </div>
      {error && (
        <p className="text-xs text-destructive" data-testid={`${id}-error`}>
          {error}
        </p>
      )}
    </div>
  );
}
