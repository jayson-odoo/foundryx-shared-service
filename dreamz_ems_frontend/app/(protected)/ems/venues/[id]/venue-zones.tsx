'use client';

/** Venue Zones editor (sprint-4/05) — sections / halls / rooms. A RESERVED
 * offering later draws its capacity_units from a zone's seats. */
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Plus, Trash2, LoaderCircleIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { SearchSelect } from '@/components/platform/search-select';
import { registrationService } from '@/services/registration-service';
import type { VenueZone, ZoneKind } from '@/types/registration';

const KIND_OPTIONS: { value: ZoneKind; label: string }[] = [
  { value: 'hall', label: 'Hall' },
  { value: 'section', label: 'Section' },
  { value: 'room', label: 'Room' },
];

export function VenueZones({
  venueId,
  editing,
  onChanged,
}: {
  venueId: string;
  editing: boolean;
  onChanged: () => void;
}) {
  const [zones, setZones] = useState<VenueZone[]>([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState('');
  const [kind, setKind] = useState<ZoneKind>('section');
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    registrationService
      .listZones(venueId)
      .then(setZones)
      .finally(() => setLoading(false));
  }, [venueId]);

  useEffect(() => load(), [load]);

  const add = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      await registrationService.createZone(venueId, { name: name.trim(), kind });
      setName('');
      setKind('section');
      load();
      onChanged();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not add zone.');
    } finally {
      setBusy(false);
    }
  };

  const remove = async (z: VenueZone) => {
    try {
      await registrationService.deleteZone(z.id);
      load();
      onChanged();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not delete zone.');
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        <LoaderCircleIcon className="size-5 animate-spin" />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 py-2">
      {zones.length === 0 ? (
        <p className="text-muted-foreground text-sm">No zones yet.</p>
      ) : (
        <div className="flex flex-col gap-2">
          {zones.map((z) => (
            <div
              key={z.id}
              className="flex items-center justify-between rounded-lg border border-border bg-card px-4 py-3"
            >
              <div className="flex items-center gap-3">
                <span className="font-medium">{z.name}</span>
                <Badge variant="secondary" appearance="light" size="sm">{z.kind}</Badge>
                <Badge variant="info" appearance="light" size="sm">{z.seatCount} seats</Badge>
              </div>
              {editing && (
                <Button variant="ghost" size="sm" onClick={() => void remove(z)} aria-label={`Delete ${z.name}`}>
                  <Trash2 className="size-4 text-destructive" />
                </Button>
              )}
            </div>
          ))}
        </div>
      )}

      {editing && (
        <div className="flex flex-col gap-3 rounded-lg border border-dashed border-border p-4 sm:flex-row sm:items-end">
          <div className="flex-1 space-y-1.5">
            <Label htmlFor="zone-name">Zone name</Label>
            <Input id="zone-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Orchestra" />
          </div>
          <div className="w-full space-y-1.5 sm:w-40">
            <Label>Kind</Label>
            <SearchSelect value={kind} onChange={(v) => setKind((v as ZoneKind) || 'section')} options={KIND_OPTIONS} />
          </div>
          <Button onClick={() => void add()} disabled={!name.trim() || busy}>
            <Plus className="size-4" /> Add zone
          </Button>
        </div>
      )}
    </div>
  );
}
