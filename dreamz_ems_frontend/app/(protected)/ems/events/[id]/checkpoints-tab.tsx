'use client';

/** Check-in tab (sprint-4/05, Cluster D slice 3) — event-day check-in admin UI.
 * Two halves: a checkpoints list + create dialog, and a scan panel that posts a
 * QR token to the selected checkpoint and shows the admit/already-in/denied
 * result prominently, refreshing a live recent-scans feed below.
 *
 * Verifies AC-05-CHK-01 (chain validation) + AC-05-CHK-02 (double-entry dedup)
 * from the UI; scanning an Eligible participant's ticket here checks the ticket
 * in → the participant auto-advances to Checked-in (AC-05-CHK-03). */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import {
  CheckCircle2,
  DoorOpen,
  LoaderCircleIcon,
  Plus,
  ScanLine,
  ShieldX,
  XCircle,
} from 'lucide-react';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { SearchSelect } from '@/components/platform/search-select';
import { useCan } from '@/hooks/use-can';
import { useDatetime } from '@/hooks/use-datetime';
import { emsService } from '@/services/ems-service';
import type {
  Checkpoint,
  CheckpointCreate,
  CheckpointLog,
  ScanResult,
  TemplateChild,
} from '@/types/ems';

interface CheckpointsTabState {
  loading: boolean;
  checkpoints: Checkpoint[];
  reloadCheckpoints: () => void;
  createCheckpoint: (body: CheckpointCreate) => Promise<Checkpoint>;
  logs: CheckpointLog[];
  logsLoading: boolean;
  loadLogs: (checkpointId: string) => Promise<void>;
  scan: (checkpointId: string, qrToken: string) => Promise<ScanResult>;
}

/** Custom hook — owns all check-in data fetching/mutations for the tab. The
 * component never touches the service directly. */
function useCheckpoints(projectId: string): CheckpointsTabState {
  const [loading, setLoading] = useState(true);
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([]);
  const [logs, setLogs] = useState<CheckpointLog[]>([]);
  const [logsLoading, setLogsLoading] = useState(false);
  const [nonce, setNonce] = useState(0);

  const reloadCheckpoints = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    emsService
      .listCheckpoints(projectId)
      .then((rows) => active && setCheckpoints(rows))
      .catch(() => active && setCheckpoints([]))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [projectId, nonce]);

  const createCheckpoint = useCallback(
    async (body: CheckpointCreate) => {
      const created = await emsService.createCheckpoint(projectId, body);
      reloadCheckpoints();
      return created;
    },
    [projectId, reloadCheckpoints],
  );

  const loadLogs = useCallback(
    async (checkpointId: string) => {
      setLogsLoading(true);
      try {
        const page = await emsService.listCheckpointLogs(projectId, checkpointId);
        setLogs(page.items);
      } catch {
        setLogs([]);
      } finally {
        setLogsLoading(false);
      }
    },
    [projectId],
  );

  const scan = useCallback(
    (checkpointId: string, qrToken: string) =>
      emsService.scanTicket(projectId, checkpointId, qrToken),
    [projectId],
  );

  // Memoize the return so its identity is stable across renders — every field
  // is either state or a useCallback, so consumers can safely list the object
  // (or its members) in effect deps without churning. Without this the bare
  // object literal changed identity every render, re-firing ScanPanel's
  // load-logs effect (which also wiped the scan-result banner) on every render.
  return useMemo(
    () => ({
      loading,
      checkpoints,
      reloadCheckpoints,
      createCheckpoint,
      logs,
      logsLoading,
      loadLogs,
      scan,
    }),
    [
      loading,
      checkpoints,
      reloadCheckpoints,
      createCheckpoint,
      logs,
      logsLoading,
      loadLogs,
      scan,
    ],
  );
}

export function CheckpointsTab({
  projectId,
  segments,
}: {
  projectId: string;
  segments: TemplateChild[];
}) {
  const { can } = useCan();
  const canManage = can('checkpoints.manage');
  const state = useCheckpoints(projectId);
  const [creating, setCreating] = useState(false);

  if (state.loading) {
    return (
      <div className="flex items-center justify-center py-16 text-muted-foreground">
        <LoaderCircleIcon className="size-6 animate-spin" />
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-6 py-2 lg:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
      {/* ── checkpoints list + create ─────────────────────────────────────── */}
      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold">Checkpoints</h3>
          {canManage && (
            <Button size="sm" variant="outline" onClick={() => setCreating(true)}>
              <Plus className="size-4" /> New checkpoint
            </Button>
          )}
        </div>
        {state.checkpoints.length === 0 ? (
          <div className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
            No checkpoints yet.
          </div>
        ) : (
          <ul className="flex flex-col gap-2">
            {state.checkpoints.map((cp) => {
              const seg = segments.find((s) => s.id === cp.segmentId);
              return (
                <li
                  key={cp.id}
                  className="flex items-center gap-3 rounded-lg border bg-card p-3"
                >
                  <DoorOpen className="size-5 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">{cp.name}</div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
                      <Badge variant="secondary" appearance="light" size="sm">
                        Single entry
                      </Badge>
                      {seg && (
                        <Badge variant="primary" appearance="light" size="sm">
                          {seg.name}
                        </Badge>
                      )}
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {/* ── scan panel + recent scans ─────────────────────────────────────── */}
      <ScanPanel checkpoints={state.checkpoints} state={state} />

      {creating && (
        <CreateCheckpointDialog
          segments={segments}
          onClose={() => setCreating(false)}
          onCreate={state.createCheckpoint}
        />
      )}
    </div>
  );
}

/* ── scan panel ─────────────────────────────────────────────────────────── */

const RESULT_STYLE: Record<
  ScanResult['result'],
  { label: string; cls: string; Icon: typeof CheckCircle2 }
> = {
  admitted: {
    label: 'Admitted',
    cls: 'border-green-500/40 bg-green-500/10 text-green-700 dark:text-green-400',
    Icon: CheckCircle2,
  },
  already_in: {
    label: 'Already checked in',
    cls: 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400',
    Icon: ShieldX,
  },
  denied: {
    label: 'Denied',
    cls: 'border-destructive/40 bg-destructive/10 text-destructive',
    Icon: XCircle,
  },
};

function ScanPanel({
  checkpoints,
  state,
}: {
  checkpoints: Checkpoint[];
  state: CheckpointsTabState;
}) {
  const { formatDateTime } = useDatetime();
  const { loadLogs, scan } = state;
  const [checkpointId, setCheckpointId] = useState<string | null>(
    checkpoints[0]?.id ?? null,
  );
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ScanResult | null>(null);

  // Keep a valid selection as checkpoints load/change.
  useEffect(() => {
    if (!checkpointId && checkpoints.length > 0) setCheckpointId(checkpoints[0].id);
  }, [checkpoints, checkpointId]);

  // Reset the result + load the recent-scans feed ONLY when the selected
  // checkpoint actually changes. Depend on the specific primitive (checkpointId)
  // and the stable loadLogs callback — never the whole state object, whose own
  // logs/logsLoading mutations would otherwise re-fire this and wipe the banner.
  useEffect(() => {
    if (checkpointId) void loadLogs(checkpointId);
    setResult(null);
  }, [checkpointId, loadLogs]);

  const onScan = useCallback(async () => {
    if (!checkpointId || !token.trim()) return;
    setBusy(true);
    try {
      const res = await scan(checkpointId, token.trim());
      setResult(res);
      setToken('');
      await loadLogs(checkpointId);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Scan failed.');
    } finally {
      setBusy(false);
    }
  }, [checkpointId, token, scan, loadLogs]);

  const checkpointOptions = useMemo(
    () => checkpoints.map((c) => ({ value: c.id, label: c.name })),
    [checkpoints],
  );

  if (checkpoints.length === 0) {
    return (
      <section className="flex items-center justify-center rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
        Create a checkpoint to start checking attendees in.
      </section>
    );
  }

  const style = result ? RESULT_STYLE[result.result] : null;

  return (
    <section className="flex flex-col gap-4">
      <div className="rounded-lg border bg-card p-4">
        <div className="mb-3 flex items-center gap-2">
          <ScanLine className="size-5 text-primary" />
          <h3 className="text-sm font-semibold">Scan a ticket</h3>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label>Checkpoint</Label>
            <SearchSelect
              value={checkpointId}
              onChange={setCheckpointId}
              options={checkpointOptions}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="qr-token">QR token</Label>
            <Input
              id="qr-token"
              value={token}
              placeholder="Paste or type the ticket QR token"
              onChange={(e) => setToken(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !busy) {
                  e.preventDefault();
                  void onScan();
                }
              }}
            />
          </div>
        </div>
        <div className="mt-3 flex justify-end">
          <Button onClick={() => void onScan()} disabled={!checkpointId || !token.trim() || busy}>
            {busy ? <LoaderCircleIcon className="size-4 animate-spin" /> : <ScanLine className="size-4" />}
            Check in
          </Button>
        </div>

        {/* prominent result banner */}
        {style && (
          <div className={`mt-4 flex items-start gap-3 rounded-lg border p-4 ${style.cls}`}>
            <style.Icon className="mt-0.5 size-6 shrink-0" />
            <div className="min-w-0">
              <div className="text-base font-semibold">{style.label}</div>
              {result?.reason && <div className="mt-0.5 text-sm">{result.reason}</div>}
            </div>
          </div>
        )}
      </div>

      {/* recent scans feed */}
      <div className="rounded-lg border bg-card">
        <div className="flex items-center justify-between border-b px-4 py-3">
          <h3 className="text-sm font-semibold">Recent scans</h3>
          {state.logsLoading && <LoaderCircleIcon className="size-4 animate-spin text-muted-foreground" />}
        </div>
        {state.logs.length === 0 ? (
          <div className="p-6 text-center text-sm text-muted-foreground">No scans yet.</div>
        ) : (
          <ul className="divide-y">
            {state.logs.map((log) => {
              const s = RESULT_STYLE[log.result];
              return (
                <li key={log.id} className="flex items-center gap-3 px-4 py-3">
                  <s.Icon
                    className={`size-5 shrink-0 ${
                      log.result === 'admitted'
                        ? 'text-green-600 dark:text-green-400'
                        : log.result === 'already_in'
                          ? 'text-amber-600 dark:text-amber-400'
                          : 'text-destructive'
                    }`}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">
                      {log.attendeeName || 'Unknown attendee'}
                    </div>
                    {log.reason && (
                      <div className="truncate text-xs text-muted-foreground">{log.reason}</div>
                    )}
                  </div>
                  <div className="shrink-0 text-right">
                    <Badge
                      variant={
                        log.result === 'admitted'
                          ? 'success'
                          : log.result === 'already_in'
                            ? 'warning'
                            : 'destructive'
                      }
                      appearance="light"
                      size="sm"
                    >
                      {s.label}
                    </Badge>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {formatDateTime(log.scannedAt)}
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}

/* ── create dialog ──────────────────────────────────────────────────────── */

function CreateCheckpointDialog({
  segments,
  onClose,
  onCreate,
}: {
  segments: TemplateChild[];
  onClose: () => void;
  onCreate: (body: CheckpointCreate) => Promise<Checkpoint>;
}) {
  const [name, setName] = useState('');
  const [segmentId, setSegmentId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await onCreate({ name: name.trim(), segmentId: segmentId ?? undefined });
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not create the checkpoint.');
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>New checkpoint</DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="cp-name">Name *</Label>
            <Input
              id="cp-name"
              value={name}
              placeholder="Main entrance"
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          {segments.length > 0 && (
            <div className="space-y-1.5">
              <Label>Gate by segment</Label>
              <SearchSelect
                value={segmentId}
                onChange={setSegmentId}
                options={segments.map((s) => ({ value: s.id, label: s.name }))}
                placeholder="Any segment"
              />
            </div>
          )}
          {/* Entry type is fixed single-entry in this release (foolproof-UI: no
              broken multi option). Shown read-only for transparency. */}
          <div className="space-y-1.5">
            <Label>Entry type</Label>
            <Badge variant="secondary" appearance="light" size="sm">
              Single entry
            </Badge>
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void save()} disabled={!name.trim() || busy}>
            {busy ? 'Saving…' : 'Create'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
