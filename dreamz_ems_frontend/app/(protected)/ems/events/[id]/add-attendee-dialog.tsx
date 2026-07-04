'use client';

/** Admin add-one (AC-05-CART-09) — register a single attendee into an event from
 * the Tickets tab. Mints a participant + signed-QR ticket + ONE Draft invoice
 * (skipped when Complimentary) via the same atomic CheckoutService.confirm the
 * public flow uses. Mirrors the AddParticipantDialog pattern in event-detail. */
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
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
import { Switch } from '@/components/ui/switch';
import { SearchSelect, type SearchSelectOption } from '@/components/platform/search-select';
import { registrationService } from '@/services/registration-service';
import { eventBillingService } from '@/services/event-billing-service';
import { formatMoney } from '@/lib/money';
import type { CapacityUnit, Offering } from '@/types/registration';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** Free capacity remaining for an offering (GA: counter; RESERVED: free units). */
function remainingFor(o: Offering): number {
  if (o.allocationMode === 'RESERVED') return Math.max(o.unitCount - o.soldCount - o.heldCount, 0);
  return Math.max(o.capacity - o.soldCount - o.heldCount, 0);
}

function offeringLabel(o: Offering): string {
  const price = o.price == null ? 'default price' : formatMoney(o.price, o.currency);
  const remaining = remainingFor(o);
  return `${o.productName} · ${price} · ${remaining} left`;
}

export function AddAttendeeDialog({
  projectId,
  onClose,
  onSaved,
}: {
  projectId: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [offerings, setOfferings] = useState<Offering[]>([]);
  const [loadingOfferings, setLoadingOfferings] = useState(true);

  const [offeringId, setOfferingId] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [comp, setComp] = useState(false);

  // RESERVED seat picker
  const [seats, setSeats] = useState<CapacityUnit[]>([]);
  const [loadingSeats, setLoadingSeats] = useState(false);
  const [capacityUnitId, setCapacityUnitId] = useState<string | null>(null);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    registrationService
      .listOfferings(projectId)
      .then(setOfferings)
      .catch(() => setOfferings([]))
      .finally(() => setLoadingOfferings(false));
  }, [projectId]);

  const selected = useMemo(
    () => offerings.find((o) => o.id === offeringId) ?? null,
    [offerings, offeringId],
  );
  const isReserved = selected?.allocationMode === 'RESERVED';

  // Foolproof-UI: only offer offerings that still have capacity.
  const offeringOptions = useMemo<SearchSelectOption[]>(
    () => offerings.filter((o) => remainingFor(o) > 0).map((o) => ({ value: o.id, label: offeringLabel(o) })),
    [offerings],
  );

  // Load free seats whenever a RESERVED offering is picked.
  useEffect(() => {
    setCapacityUnitId(null);
    if (!selected || selected.allocationMode !== 'RESERVED') {
      setSeats([]);
      return;
    }
    setLoadingSeats(true);
    registrationService
      .listCapacityUnits(projectId, selected.id)
      .then((units) => setSeats(units.filter((u) => u.status === 'free')))
      .catch(() => setSeats([]))
      .finally(() => setLoadingSeats(false));
  }, [projectId, selected]);

  const seatOptions = useMemo<SearchSelectOption[]>(
    () => seats.map((u) => ({ value: u.id, label: u.zone ? `${u.zone} · ${u.label}` : u.label })),
    [seats],
  );

  const emailValid = EMAIL_RE.test(email.trim());
  const seatOk = !isReserved || capacityUnitId != null;
  const canSubmit = !!offeringId && emailValid && seatOk && !busy;

  const save = async () => {
    if (!offeringId || !emailValid || !seatOk) return;
    setBusy(true);
    setError(null);
    try {
      const result = await eventBillingService.adminRegister(projectId, {
        items: [
          {
            offeringId,
            attendee: {
              email: email.trim(),
              ...(name.trim() ? { name: name.trim() } : {}),
              ...(phone.trim() ? { phone: phone.trim() } : {}),
            },
            ...(isReserved && capacityUnitId ? { capacityUnitId } : {}),
          },
        ],
        comp,
      });
      toast.success(
        comp
          ? `Comp ticket issued (${result.orderRef}).`
          : `Attendee registered — ${result.orderRef}, ${formatMoney(result.total, result.currency)} invoice.`,
      );
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not register the attendee.');
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Add attendee</DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-4">
          {!loadingOfferings && offeringOptions.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              {offerings.length === 0
                ? 'Create an offering first.'
                : 'No offering has remaining capacity.'}
            </p>
          ) : (
            <>
              <div className="space-y-1.5">
                <Label>Offering *</Label>
                <SearchSelect
                  value={offeringId}
                  onChange={setOfferingId}
                  options={offeringOptions}
                  placeholder={loadingOfferings ? 'Loading…' : 'Select an offering'}
                  disabled={loadingOfferings}
                  ariaLabel="Offering"
                />
              </div>

              {isReserved && (
                <div className="space-y-1.5">
                  <Label>Seat *</Label>
                  <SearchSelect
                    value={capacityUnitId}
                    onChange={setCapacityUnitId}
                    options={seatOptions}
                    placeholder={
                      loadingSeats
                        ? 'Loading seats…'
                        : seatOptions.length === 0
                          ? 'No free seats'
                          : 'Select a seat'
                    }
                    disabled={loadingSeats || seatOptions.length === 0}
                    ariaLabel="Seat"
                  />
                </div>
              )}

              <div className="space-y-1.5">
                <Label>Name</Label>
                <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Optional" />
              </div>
              <div className="space-y-1.5">
                <Label>Email *</Label>
                <Input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  aria-invalid={email.length > 0 && !emailValid}
                />
                {email.length > 0 && !emailValid && (
                  <p className="text-destructive text-xs">Enter a valid email address.</p>
                )}
              </div>
              <div className="space-y-1.5">
                <Label>Phone</Label>
                <Input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="Optional" />
              </div>

              <div className="flex items-center justify-between rounded-lg border border-border px-3 py-2.5">
                <Label htmlFor="comp-toggle" className="cursor-pointer">
                  Complimentary (no invoice)
                </Label>
                <Switch id="comp-toggle" checked={comp} onCheckedChange={setComp} />
              </div>
            </>
          )}
          {error && <p className="text-destructive text-sm">{error}</p>}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void save()} disabled={!canSubmit}>
            {busy ? 'Registering…' : 'Add attendee'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
