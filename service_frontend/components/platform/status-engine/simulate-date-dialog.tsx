'use client';

/**
 * Admin date-simulation (sprint-4/03 Slice 6) - fast-forward / backtrack "now"
 * to test time-based derived status without waiting. Preview = dry-run (nothing
 * persists); Apply commits the would-advance transitions. Gated statuses.manage.
 */
import { useState } from 'react';
import { toast } from 'sonner';
import { LoaderCircleIcon } from 'lucide-react';
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
import { statusEngineService } from '@/services/status-engine-service';
import type { SimulateRow, StatusNodeData } from '@/types/status-engine';

export interface SimulateDateDialogProps {
  entityType: string;
  entityLabel: string;
  statuses: StatusNodeData[];
  onClose: () => void;
}

export function SimulateDateDialog({
  entityType,
  entityLabel,
  statuses,
  onClose,
}: SimulateDateDialogProps) {
  const [asOf, setAsOf] = useState('');
  const [rows, setRows] = useState<SimulateRow[] | null>(null);
  const [busy, setBusy] = useState(false);

  const label = (id: string | null) =>
    (id ? statuses.find((s) => s.id === id)?.label : null) ?? '-';

  const run = async (apply: boolean) => {
    if (!asOf) return;
    setBusy(true);
    try {
      const res = await statusEngineService.simulate(entityType, asOf, apply);
      setRows(res.data);
      if (apply) {
        toast.success(
          res.data.length
            ? `Applied - ${res.data.length} ${entityLabel.toLowerCase()} record(s) advanced.`
            : 'Nothing to advance as of that date.',
        );
        onClose();
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Simulation failed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Simulate date - {entityLabel}</DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="sim-asof">Evaluate as if today were</Label>
            <Input
              id="sim-asof"
              type="date"
              value={asOf}
              onChange={(e) => {
                setAsOf(e.target.value);
                setRows(null);
              }}
              aria-label="As-of date"
            />
          </div>

          {rows !== null && (
            <div className="rounded-lg border">
              <div className="border-b px-3 py-2 text-sm font-medium">
                {rows.length
                  ? `${rows.length} record(s) would advance`
                  : 'No records would advance as of that date.'}
              </div>
              {rows.length > 0 && (
                <ul className="max-h-64 divide-y overflow-y-auto text-sm">
                  {rows.map((r) => (
                    <li key={r.id} className="flex items-center justify-between gap-3 px-3 py-2">
                      <span className="truncate font-medium">{r.label}</span>
                      <span className="shrink-0 text-muted-foreground">
                        {label(r.fromId)} → {label(r.toId)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant="outline" onClick={() => void run(false)} disabled={!asOf || busy}>
            {busy ? <LoaderCircleIcon className="size-4 animate-spin" /> : 'Preview'}
          </Button>
          <Button
            onClick={() => void run(true)}
            disabled={!asOf || busy || !rows?.length}
          >
            Apply
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
