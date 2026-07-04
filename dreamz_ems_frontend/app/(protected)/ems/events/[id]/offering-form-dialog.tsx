'use client';

/** Offering create/edit (sprint-4/05, Cluster D). An offering prices a core
 * catalog product for THIS event: GA (counter capacity) or RESERVED (seats minted
 * from a venue's zones → capacity_units). Grants a segment/role onto the
 * participant at mint; caps tickets per attendee (R3-7). */
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { Armchair } from 'lucide-react';
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
import { MultiSelect } from '@/components/platform/multi-select';
import { emsService } from '@/services/ems-service';
import { registrationService } from '@/services/registration-service';
import { CURRENCY_OPTIONS } from '@/lib/money';
import type { Product, TemplateChild } from '@/types/ems';
import type {
  AllocationMode,
  CapacityUnit,
  Offering,
  Venue,
  VenueZone,
} from '@/types/registration';

const NONE = '__none__';

const ALLOCATION_OPTIONS: { value: AllocationMode; label: string }[] = [
  { value: 'GA', label: 'General admission (counter)' },
  { value: 'RESERVED', label: 'Reserved seating (seat map)' },
];

export function OfferingFormDialog({
  projectId,
  offering,
  roles,
  segments,
  onClose,
  onSaved,
}: {
  projectId: string;
  offering: Offering | null; // null = create
  roles: TemplateChild[];
  segments: TemplateChild[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const editing = !!offering;

  const [products, setProducts] = useState<Product[]>([]);
  const [venues, setVenues] = useState<Venue[]>([]);
  const [zones, setZones] = useState<VenueZone[]>([]);
  const [units, setUnits] = useState<CapacityUnit[]>([]);

  const [productId, setProductId] = useState<string | null>(offering?.productId ?? null);
  const [price, setPrice] = useState(offering?.price == null ? '' : String(offering.price));
  const [currency, setCurrency] = useState(offering?.currency ?? '');
  const [taxRate, setTaxRate] = useState(offering ? String(offering.taxRate) : '9');
  const [capacity, setCapacity] = useState(offering ? String(offering.capacity) : '100');
  const [mode, setMode] = useState<AllocationMode>(offering?.allocationMode ?? 'GA');
  const [validFrom, setValidFrom] = useState(offering?.validFrom ?? '');
  const [validUntil, setValidUntil] = useState(offering?.validUntil ?? '');
  const [grantsSegmentId, setGrantsSegmentId] = useState<string | null>(offering?.grantsSegmentId ?? null);
  const [grantsRoleId, setGrantsRoleId] = useState<string | null>(offering?.grantsRoleId ?? null);
  const [maxPerAttendee, setMaxPerAttendee] = useState(
    offering?.maxTicketsPerAttendee == null ? '' : String(offering.maxTicketsPerAttendee),
  );
  const [venueId, setVenueId] = useState<string | null>(offering?.venueId ?? null);
  const [zoneIds, setZoneIds] = useState<string[]>(offering?.zoneIds ?? []);

  const [busy, setBusy] = useState(false);
  const [minting, setMinting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    emsService.productOptions().then(setProducts).catch(() => setProducts([]));
    registrationService.listVenuesQuery({ page: 0, pageSize: 200 }).then((r) => setVenues(r.data)).catch(() => setVenues([]));
    if (offering) registrationService.listCapacityUnits(projectId, offering.id).then(setUnits).catch(() => setUnits([]));
    // New offering → default the price currency to the tenant's default currency.
    else emsService.getTenantSettings().then((s) => setCurrency((c) => c || s.defaultCurrency)).catch(() => {});
  }, [offering, projectId]);

  useEffect(() => {
    if (!venueId) {
      setZones([]);
      return;
    }
    registrationService.listZones(venueId).then(setZones).catch(() => setZones([]));
  }, [venueId]);

  const save = async () => {
    if (!productId) {
      setError('Pick a product.');
      return;
    }
    if (mode === 'RESERVED' && (!venueId || zoneIds.length === 0)) {
      setError('Reserved offerings need a venue and at least one zone.');
      return;
    }
    setBusy(true);
    setError(null);
    const body = {
      productId,
      price: price === '' ? null : Number(price),
      currency,
      taxRate: Number(taxRate) || 0,
      capacity: Number(capacity) || 0,
      allocationMode: mode,
      validFrom: validFrom || null,
      validUntil: validUntil || null,
      grantsSegmentId: grantsSegmentId === NONE ? null : grantsSegmentId,
      grantsRoleId: grantsRoleId === NONE ? null : grantsRoleId,
      maxTicketsPerAttendee: maxPerAttendee === '' ? null : Number(maxPerAttendee),
      venueId: mode === 'RESERVED' ? venueId : null,
      zoneIds: mode === 'RESERVED' ? zoneIds : [],
    };
    try {
      if (offering) await registrationService.updateOffering(projectId, offering.id, body);
      else await registrationService.createOffering(projectId, body);
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save.');
      setBusy(false);
    }
  };

  const mint = async () => {
    if (!offering) return;
    setMinting(true);
    try {
      const minted = await registrationService.mintCapacityUnits(projectId, offering.id);
      setUnits(minted);
      toast.success(`Minted ${minted.length} seats.`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not mint seats.');
    } finally {
      setMinting(false);
    }
  };

  const zoneSeatTotal = useMemo(
    () => zones.filter((z) => zoneIds.includes(z.id)).reduce((sum, z) => sum + z.seatCount, 0),
    [zones, zoneIds],
  );

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{editing ? 'Edit offering' : 'New offering'}</DialogTitle>
        </DialogHeader>
        <DialogBody className="max-h-[70vh] space-y-4 overflow-y-auto">
          <Field label="Product *">
            <SearchSelect
              value={productId}
              onChange={setProductId}
              options={products.map((p) => ({ value: p.id, label: p.name }))}
              placeholder="Pick a catalog product"
            />
          </Field>

          <Field label="Allocation">
            <SearchSelect value={mode} onChange={(v) => setMode((v as AllocationMode) || 'GA')} options={ALLOCATION_OPTIONS} />
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Price override">
              <div className="flex gap-2">
                <div className="w-24 shrink-0">
                  <SearchSelect value={currency} onChange={(v) => setCurrency(v || 'SGD')} options={CURRENCY_OPTIONS} />
                </div>
                <Input type="number" value={price} onChange={(e) => setPrice(e.target.value)} placeholder="default" />
              </div>
            </Field>
            <Field label="Tax rate (%)">
              <Input type="number" value={taxRate} onChange={(e) => setTaxRate(e.target.value)} />
            </Field>
          </div>

          {mode === 'GA' ? (
            <Field label="Capacity">
              <Input type="number" value={capacity} onChange={(e) => setCapacity(e.target.value)} />
            </Field>
          ) : (
            <>
              <Field label="Venue *">
                <SearchSelect
                  value={venueId}
                  onChange={(v) => { setVenueId(v); setZoneIds([]); }}
                  options={venues.map((v) => ({ value: v.id, label: v.name }))}
                  placeholder="Pick a venue"
                />
              </Field>
              {venueId && (
                <Field label="Zones *">
                  <MultiSelect
                    options={zones.map((z) => ({ value: z.id, label: `${z.name} (${z.seatCount})` }))}
                    value={zoneIds}
                    onChange={setZoneIds}
                    placeholder="Pick zones to draw seats from"
                  />
                </Field>
              )}
              {mode === 'RESERVED' && (
                <div className="flex items-center justify-between rounded-lg border border-border bg-muted/30 px-4 py-3">
                  <div className="flex items-center gap-2 text-sm">
                    <Armchair className="size-4 text-muted-foreground" />
                    {units.length > 0 ? (
                      <span><span className="font-medium">{units.length}</span> seats minted</span>
                    ) : (
                      <span className="text-muted-foreground">{zoneSeatTotal} seats available to mint</span>
                    )}
                  </div>
                  {editing && (
                    <Button variant="outline" size="sm" onClick={() => void mint()} disabled={minting || zoneIds.length === 0}>
                      {minting ? 'Minting…' : units.length > 0 ? 'Re-mint' : 'Mint seats'}
                    </Button>
                  )}
                </div>
              )}
              {!editing && (
                <p className="text-muted-foreground text-xs">Save first, then mint the seats.</p>
              )}
            </>
          )}

          <div className="grid grid-cols-2 gap-3">
            <Field label="Valid from">
              <Input type="date" value={validFrom} onChange={(e) => setValidFrom(e.target.value)} />
            </Field>
            <Field label="Valid until">
              <Input type="date" value={validUntil} onChange={(e) => setValidUntil(e.target.value)} />
            </Field>
          </div>

          {segments.length > 0 && (
            <Field label="Grants segment">
              <SearchSelect
                value={grantsSegmentId ?? NONE}
                onChange={setGrantsSegmentId}
                options={[{ value: NONE, label: 'None' }, ...segments.map((s) => ({ value: s.id, label: s.name }))]}
              />
            </Field>
          )}
          {roles.length > 0 && (
            <Field label="Grants role">
              <SearchSelect
                value={grantsRoleId ?? NONE}
                onChange={setGrantsRoleId}
                options={[{ value: NONE, label: 'None' }, ...roles.map((r) => ({ value: r.id, label: r.name }))]}
              />
            </Field>
          )}
          <Field label="Max tickets / attendee">
            <Input type="number" value={maxPerAttendee} onChange={(e) => setMaxPerAttendee(e.target.value)} placeholder="unlimited" />
          </Field>

          {error && <p className="text-destructive text-sm">{error}</p>}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button onClick={() => void save()} disabled={!productId || busy}>
            {busy ? 'Saving…' : editing ? 'Save' : 'Create'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      {children}
    </div>
  );
}

/** Tiny status legend reused by the list's RESERVED preview. */
export function UnitStatusBadge({ status }: { status: CapacityUnit['status'] }) {
  if (status === 'sold') return <Badge variant="secondary" appearance="light" size="sm">Sold</Badge>;
  if (status === 'held') return <Badge variant="warning" appearance="light" size="sm">Held</Badge>;
  return <Badge variant="success" appearance="light" size="sm">Free</Badge>;
}
