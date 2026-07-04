'use client';

/** Record-payment dialog (sprint-4/07 Cluster F slice 1, AC-07-10). Manual
 * CASH/CARD/BANK only — those are the only options offered (foolproof-UI; gateway
 * payments are webhook-created). Amount defaults to the outstanding balance and
 * is capped at it (overpayment is also the backend boundary, AC-07-12). */
import { useMemo, useState } from 'react';
import { toast } from 'sonner';
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
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { SearchSelect } from '@/components/platform/search-select';
import { financeService } from '@/services/finance-service';
import { formatMoney } from '@/lib/money';
import type { Invoice, PaymentMethod } from '@/types/registration';

const METHOD_OPTIONS = [
  { value: 'CASH', label: 'Cash' },
  { value: 'CARD', label: 'Card' },
  { value: 'BANK', label: 'Bank transfer' },
];

export function RecordPaymentDialog({
  invoice,
  open,
  onOpenChange,
  onRecorded,
}: {
  invoice: Invoice;
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onRecorded: (updated: Invoice) => void;
}) {
  const balance = useMemo(
    () => Math.max(0, Number((invoice.total - invoice.paidTotal).toFixed(4))),
    [invoice.total, invoice.paidTotal],
  );
  const [amount, setAmount] = useState<string>(balance.toFixed(2));
  const [method, setMethod] = useState<PaymentMethod>('CASH');
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);

  const amountNum = Number(amount);
  const invalid = !Number.isFinite(amountNum) || amountNum <= 0 || amountNum > balance + 1e-9;

  async function submit() {
    setSaving(true);
    try {
      const updated = await financeService.recordPayment(invoice.id, {
        amount: amountNum,
        method,
        note: note || undefined,
      });
      onRecorded(updated);
      onOpenChange(false);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not record the payment.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Record payment</DialogTitle>
          <DialogDescription>
            Balance due {formatMoney(balance, invoice.currency)}
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="pay-amount">Amount</Label>
            <Input
              id="pay-amount"
              type="number"
              min={0}
              step="0.01"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label>Method</Label>
            <SearchSelect
              options={METHOD_OPTIONS}
              value={method}
              onChange={(v) => setMethod(v as PaymentMethod)}
              ariaLabel="Payment method"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="pay-note">Note</Label>
            <Input id="pay-note" value={note} onChange={(e) => setNote(e.target.value)} />
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={saving || invalid}>
            Record payment
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
