'use client';

/** Refund dialog (sprint-4/07 Cluster F slice 4, AC-07-37/38). The operator picks
 * which tickets to refund (only refundable ones are selectable — foolproof-UI).
 * The refund method MIRRORS the payment method server-side (gateway vs manual);
 * over-refund is the backend boundary. On success the invoice re-derives. */
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { LoaderCircleIcon } from 'lucide-react';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { financeService } from '@/services/finance-service';
import type { Invoice, RefundableTicket } from '@/types/registration';

export function RefundDialog({
  invoice,
  open,
  onOpenChange,
  onRefunded,
}: {
  invoice: Invoice;
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onRefunded: () => void;
}) {
  const [tickets, setTickets] = useState<RefundableTicket[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    setTickets(null);
    financeService
      .refundableTickets(invoice.id)
      .then(setTickets)
      .catch((e) => toast.error(e instanceof Error ? e.message : 'Could not load tickets.'));
  }, [invoice.id]);

  useEffect(() => {
    if (open) {
      setSelected(new Set());
      setReason('');
      load();
    }
  }, [open, load]);

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const refundable = (tickets ?? []).filter((t) => t.refundable);

  async function submit() {
    setSaving(true);
    try {
      await financeService.createRefund(invoice.id, Array.from(selected), reason || undefined);
      toast.success('Refund processed.');
      onRefunded();
      onOpenChange(false);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not process the refund.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Refund tickets</DialogTitle>
          <DialogDescription>Select the tickets to refund on this invoice.</DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          {tickets === null ? (
            <div className="flex items-center justify-center py-8 text-muted-foreground">
              <LoaderCircleIcon className="size-5 animate-spin" />
            </div>
          ) : refundable.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              No refundable tickets on this invoice.
            </p>
          ) : (
            <div className="space-y-1.5">
              {(tickets ?? []).map((t) => (
                <label
                  key={t.id}
                  className={`flex items-center gap-3 rounded-md border border-border px-3 py-2 text-sm ${
                    t.refundable ? 'cursor-pointer hover:bg-muted/40' : 'opacity-50'
                  }`}
                >
                  <Checkbox
                    checked={selected.has(t.id)}
                    onCheckedChange={() => t.refundable && toggle(t.id)}
                    disabled={!t.refundable}
                  />
                  <span className="font-mono text-xs">{t.id.slice(0, 8)}</span>
                  <Badge variant="secondary" appearance="light" size="sm" className="ms-auto">
                    {t.status}
                  </Badge>
                </label>
              ))}
            </div>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="refund-reason">Reason</Label>
            <Input id="refund-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={saving || selected.size === 0}>
            Refund {selected.size > 0 ? `(${selected.size})` : ''}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
