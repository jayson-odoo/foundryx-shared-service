'use client';

/** Event settlement tab (sprint-4/07 Cluster F slice 4, AC-07-46/47). Shows the
 * AGENCY give-back settlement: a three-line net (gross − gateway fees − fee), the
 * Generate action (when none exists), and the Draft→Approved→Remitted lifecycle.
 * Supplementary ADJUSTMENTs (post-remit refunds) are listed below the PRIMARY. */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { ArrowRight, Banknote, LoaderCircleIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useStatusGraph } from '@/hooks/use-status-engine';
import { useCan } from '@/hooks/use-can';
import { financeService } from '@/services/finance-service';
import { formatMoney } from '@/lib/money';
import type { Settlement } from '@/types/registration';
import type { StatusTransition } from '@/types/status-engine';

const CURRENCY = 'MYR';

export function SettlementTab({ projectId }: { projectId: string }) {
  const { can } = useCan();
  const canManage = can('settlements.manage');
  const engine = useStatusGraph('settlement');
  const [settlements, setSettlements] = useState<Settlement[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [remitFor, setRemitFor] = useState<Settlement | null>(null);

  const load = useCallback(() => {
    financeService
      .listSettlements(projectId)
      .then(setSettlements)
      .catch((e) => {
        toast.error(e instanceof Error ? e.message : 'Could not load settlements.');
        setSettlements([]);
      });
  }, [projectId]);
  useEffect(() => load(), [load]);

  const primary = useMemo(
    () => (settlements ?? []).find((s) => s.kind === 'PRIMARY') ?? null,
    [settlements],
  );
  const adjustments = useMemo(
    () => (settlements ?? []).filter((s) => s.kind === 'ADJUSTMENT'),
    [settlements],
  );

  const statusLabel = useMemo(
    () => new Map((engine.graph?.statuses ?? []).map((s) => [s.id, s.label])),
    [engine.graph],
  );

  async function generate() {
    setBusy(true);
    try {
      await financeService.generateSettlement(projectId);
      toast.success('Settlement generated.');
      load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not generate the settlement.');
    } finally {
      setBusy(false);
    }
  }

  async function transition(s: Settlement, toStatusId: string, key: string) {
    if (key === 'remitted') {
      setRemitFor(s);
      return;
    }
    try {
      await financeService.transitionSettlement(s.id, toStatusId);
      load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not change the status.');
    }
  }

  if (settlements === null) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        <LoaderCircleIcon className="size-5 animate-spin" />
      </div>
    );
  }

  if (!primary) {
    return (
      <div className="flex flex-col items-center gap-4 py-12 text-center">
        <Banknote className="size-8 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">No settlement generated yet.</p>
        {canManage && (
          <Button onClick={generate} disabled={busy}>
            {busy ? 'Generating…' : 'Generate settlement'}
          </Button>
        )}
      </div>
    );
  }

  return (
    <div className="max-w-2xl space-y-6">
      <SettlementCard
        settlement={primary}
        statusLabel={statusLabel}
        transitions={engine.graph?.transitions ?? []}
        canManage={canManage}
        onTransition={transition}
      />
      {adjustments.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-sm font-semibold text-muted-foreground">Adjustments</h3>
          {adjustments.map((a) => (
            <SettlementCard
              key={a.id}
              settlement={a}
              statusLabel={statusLabel}
              transitions={engine.graph?.transitions ?? []}
              canManage={canManage}
              onTransition={transition}
            />
          ))}
        </div>
      )}
      {remitFor && (
        <RemitDialog
          settlement={remitFor}
          statusId={
            (engine.graph?.transitions ?? []).find(
              (t) => t.fromStatusId === remitFor.statusId && statusLabel.get(t.toStatusId) === 'Remitted',
            )?.toStatusId ?? ''
          }
          onClose={() => setRemitFor(null)}
          onDone={() => {
            setRemitFor(null);
            load();
          }}
        />
      )}
    </div>
  );
}

function SettlementCard({
  settlement: s,
  statusLabel,
  transitions,
  canManage,
  onTransition,
}: {
  settlement: Settlement;
  statusLabel: Map<string, string>;
  transitions: StatusTransition[];
  canManage: boolean;
  onTransition: (s: Settlement, toStatusId: string, key: string) => void;
}) {
  const moves = transitions.filter((t) => t.triggerMode !== 'auto' && t.fromStatusId === s.statusId);
  return (
    <div className="rounded-lg border border-border p-5">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-medium">{s.kind === 'PRIMARY' ? 'Settlement' : 'Adjustment'}</span>
          {s.statusLabel && (
            <Badge variant="secondary" appearance="light" size="sm">{s.statusLabel}</Badge>
          )}
          {s.remittanceRef && (
            <span className="font-mono text-xs text-muted-foreground">{s.remittanceRef}</span>
          )}
        </div>
        {canManage && moves.length > 0 && (
          <div className="flex gap-2">
            {moves.map((t) => (
              <Button
                key={t.toStatusId}
                size="sm"
                variant="outline"
                onClick={() => onTransition(s, t.toStatusId, (statusLabel.get(t.toStatusId) || '').toLowerCase())}
              >
                <ArrowRight className="size-3.5" />
                {statusLabel.get(t.toStatusId) || t.label}
              </Button>
            ))}
          </div>
        )}
      </div>
      <div className="space-y-1 text-sm">
        <div className="flex justify-between text-muted-foreground">
          <span>Gross collected</span><span>{formatMoney(s.grossCollected, CURRENCY)}</span>
        </div>
        <div className="flex justify-between text-muted-foreground">
          <span>Gateway fees</span><span>− {formatMoney(s.gatewayFees, CURRENCY)}</span>
        </div>
        <div className="flex justify-between text-muted-foreground">
          <span>Agency fee{s.feeType ? ` (${s.feeType.toLowerCase()})` : ''}</span>
          <span>− {formatMoney(s.feeAmount, CURRENCY)}</span>
        </div>
        <div className="flex justify-between border-t border-border pt-1 font-semibold">
          <span>Net payable</span><span>{formatMoney(s.netPayable, CURRENCY)}</span>
        </div>
      </div>
    </div>
  );
}

function RemitDialog({
  settlement,
  statusId,
  onClose,
  onDone,
}: {
  settlement: Settlement;
  statusId: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const [ref, setRef] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    try {
      await financeService.transitionSettlement(settlement.id, statusId, ref);
      toast.success('Settlement marked remitted.');
      onDone();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not mark remitted.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Mark remitted</DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="remit-ref">Remittance reference</Label>
            <Input id="remit-ref" value={ref} onChange={(e) => setRef(e.target.value)} />
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button onClick={submit} disabled={busy || !ref}>Mark remitted</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
