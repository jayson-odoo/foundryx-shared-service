'use client';

/** Venue detail — Details (name/address/capacity) + Zones + Seats tabs.
 * Global Edit toggle gates zone/seat mutation (read-only by default). */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import { Grid3x3, Info, LayoutGrid, LoaderCircleIcon } from 'lucide-react';
import { Container } from '@/components/common/container';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Form } from '@/components/ui/form';
import { ResourceForm } from '@/components/platform/resource-form';
import type { ResourceFormConfig } from '@/components/platform/resource-form/types';
import { useTerminology } from '@/hooks/use-terminology';
import { registrationService } from '@/services/registration-service';
import type { Venue } from '@/types/registration';
import { VenueZones } from './venue-zones';
import { SeatMap } from './seat-map';

interface DetailValues {
  name: string;
  address: string;
  capacity: string;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1.5 md:grid-cols-[200px_1fr] md:items-start md:gap-4">
      <Label className="pt-2 text-sm text-muted-foreground">{label}</Label>
      <div className="max-w-xl">{children}</div>
    </div>
  );
}

export function VenueDetail({ venueId }: { venueId: string }) {
  const { labelPlural } = useTerminology();
  const form = useForm<DetailValues>({ defaultValues: { name: '', address: '', capacity: '' } });
  const [record, setRecord] = useState<Venue | null>(null);
  const [loading, setLoading] = useState(true);
  // bump to re-read counts after zone/seat edits (keeps the header badges fresh)
  const [childNonce, setChildNonce] = useState(0);

  const reset = useCallback(
    (v: Venue) =>
      form.reset({
        name: v.name ?? '',
        address: v.address ?? '',
        capacity: v.capacity == null ? '' : String(v.capacity),
      }),
    [form],
  );

  const load = useCallback(
    () => registrationService.getVenue(venueId).then((v) => { setRecord(v); reset(v); }),
    [venueId, reset],
  );

  useEffect(() => {
    let active = true;
    load().finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [load]);

  const onChildChanged = useCallback(() => {
    registrationService.getVenue(venueId).then((v) => setRecord(v));
    setChildNonce((n) => n + 1);
  }, [venueId]);

  const values = form.watch();

  const config = useMemo<ResourceFormConfig<Venue> | null>(() => {
    if (!record) return null;
    return {
      breadcrumb: [{ label: labelPlural('venue'), href: '/ems/venues' }, { label: record.name }],
      backHref: '/ems/venues',
      backLabel: labelPlural('venue'),
      title: record.name,
      subtitle: record.address ?? undefined,
      tabs: [
        {
          id: 'details',
          label: 'Details',
          icon: Info,
          render: ({ editing }) => (
            <div className="flex flex-col gap-5 py-2">
              <Row label="Name">
                {editing ? (
                  <Input aria-label="Name" value={values.name} onChange={(e) => form.setValue('name', e.target.value, { shouldDirty: true })} />
                ) : (
                  <span className="text-sm">{values.name || '—'}</span>
                )}
              </Row>
              <Row label="Address">
                {editing ? (
                  <Input aria-label="Address" value={values.address} onChange={(e) => form.setValue('address', e.target.value, { shouldDirty: true })} />
                ) : (
                  <span className="text-sm">{values.address || '—'}</span>
                )}
              </Row>
              <Row label="Capacity">
                {editing ? (
                  <Input aria-label="Capacity" type="number" value={values.capacity} onChange={(e) => form.setValue('capacity', e.target.value, { shouldDirty: true })} />
                ) : (
                  <span className="text-sm">{values.capacity || '—'}</span>
                )}
              </Row>
              <div className="flex gap-6 pt-2 text-sm text-muted-foreground">
                <span><span className="font-medium text-foreground">{record.zoneCount}</span> zones</span>
                <span><span className="font-medium text-foreground">{record.seatCount}</span> seats</span>
              </div>
            </div>
          ),
        },
        {
          id: 'zones',
          label: 'Zones',
          icon: LayoutGrid,
          render: ({ editing }) => (
            <VenueZones key={`zones-${childNonce}`} venueId={venueId} editing={editing} onChanged={onChildChanged} />
          ),
        },
        {
          id: 'seats',
          label: 'Seats',
          icon: Grid3x3,
          render: ({ editing }) => (
            <SeatMap key={`seats-${childNonce}`} venueId={venueId} editing={editing} onChanged={onChildChanged} />
          ),
        },
      ],
      actions: [],
      actionRows: [record],
      onReload: () => load(),
      editable: true,
      editPermission: 'venues.manage',
      isDirty: form.formState.isDirty,
      onSave: async () => {
        const updated = await registrationService.updateVenue(record.id, {
          name: values.name,
          address: values.address || null,
          capacity: values.capacity === '' ? null : Number(values.capacity),
        });
        setRecord(updated);
        reset(updated);
        return true;
      },
      onCancel: () => reset(record),
    };
  }, [record, values, form, labelPlural, load, reset, venueId, childNonce, onChildChanged]);

  if (loading) {
    return (
      <Container width="fluid">
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      </Container>
    );
  }
  if (!config) {
    return (
      <Container width="fluid">
        <div className="py-24 text-center text-sm font-medium">Venue not found.</div>
      </Container>
    );
  }
  return (
    <Container width="fluid">
      <Form {...form}>
        <ResourceForm config={config} />
      </Form>
    </Container>
  );
}
