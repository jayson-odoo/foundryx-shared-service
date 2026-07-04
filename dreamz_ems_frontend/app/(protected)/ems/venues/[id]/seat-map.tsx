'use client';

/** Seat map (sprint-4/05, R3-4) — the FUNCTIONAL generator + grid: pick a zone,
 * generate N rows × M seats (auto labels + auto-grid x/y), preview the resulting
 * layout. The visual drag designer is the deferred Venue/Seating plan; this mints
 * the underlying venue_seats that RESERVED offerings draw capacity_units from. */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { Grid3x3, LoaderCircleIcon, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { SearchSelect } from '@/components/platform/search-select';
import { registrationService } from '@/services/registration-service';
import type { VenueSeat, VenueZone } from '@/types/registration';

export function SeatMap({
  venueId,
  editing,
  onChanged,
}: {
  venueId: string;
  editing: boolean;
  onChanged: () => void;
}) {
  const [zones, setZones] = useState<VenueZone[]>([]);
  const [seats, setSeats] = useState<VenueSeat[]>([]);
  const [zoneId, setZoneId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [rows, setRows] = useState('8');
  const [perRow, setPerRow] = useState('12');
  const [rowLabels, setRowLabels] = useState<'alpha' | 'numeric'>('alpha');
  const [startNumber, setStartNumber] = useState('1');
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([registrationService.listZones(venueId), registrationService.listSeats(venueId)])
      .then(([zs, ss]) => {
        setZones(zs);
        setSeats(ss);
        setZoneId((cur) => cur ?? zs[0]?.id ?? null);
      })
      .finally(() => setLoading(false));
  }, [venueId]);

  useEffect(() => load(), [load]);

  const zoneSeats = useMemo(
    () => seats.filter((s) => s.zoneId === zoneId).sort((a, b) => a.y - b.y || a.x - b.x),
    [seats, zoneId],
  );

  // group seats into rows (by y) for the preview grid
  const seatRows = useMemo(() => {
    const byRow = new Map<string, VenueSeat[]>();
    for (const s of zoneSeats) {
      const key = s.row ?? String(s.y);
      if (!byRow.has(key)) byRow.set(key, []);
      byRow.get(key)!.push(s);
    }
    return Array.from(byRow.entries());
  }, [zoneSeats]);

  const generate = async () => {
    if (!zoneId) return;
    const r = Number(rows);
    const m = Number(perRow);
    if (!r || !m || r < 1 || m < 1) {
      toast.error('Rows and seats per row must be positive.');
      return;
    }
    setBusy(true);
    try {
      await registrationService.generateSeats({
        zoneId,
        rows: r,
        perRow: m,
        rowLabels,
        startNumber: Number(startNumber) || 1,
      });
      load();
      onChanged();
      toast.success(`Generated ${r * m} seats.`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not generate seats.');
    } finally {
      setBusy(false);
    }
  };

  const clearZone = async () => {
    if (!zoneId) return;
    try {
      await registrationService.clearZoneSeats(zoneId);
      load();
      onChanged();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not clear seats.');
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        <LoaderCircleIcon className="size-5 animate-spin" />
      </div>
    );
  }

  if (zones.length === 0) {
    return <p className="text-muted-foreground py-4 text-sm">Add a zone first to lay out seats.</p>;
  }

  return (
    <div className="flex flex-col gap-5 py-2">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="w-full space-y-1.5 sm:w-64">
          <Label>Zone</Label>
          <SearchSelect
            value={zoneId}
            onChange={setZoneId}
            options={zones.map((z) => ({ value: z.id, label: `${z.name} (${z.seatCount})` }))}
          />
        </div>
        {editing && zoneSeats.length > 0 && (
          <Button variant="outline" size="sm" onClick={() => void clearZone()}>
            <Trash2 className="size-4" /> Clear zone seats
          </Button>
        )}
      </div>

      {editing && (
        <div className="grid grid-cols-2 gap-3 rounded-lg border border-dashed border-border p-4 sm:grid-cols-5 sm:items-end">
          <div className="space-y-1.5">
            <Label htmlFor="sm-rows">Rows</Label>
            <Input id="sm-rows" type="number" value={rows} onChange={(e) => setRows(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sm-per">Seats / row</Label>
            <Input id="sm-per" type="number" value={perRow} onChange={(e) => setPerRow(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label>Row labels</Label>
            <SearchSelect
              value={rowLabels}
              onChange={(v) => setRowLabels((v as 'alpha' | 'numeric') || 'alpha')}
              options={[
                { value: 'alpha', label: 'A, B, C…' },
                { value: 'numeric', label: '1, 2, 3…' },
              ]}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sm-start">Start no.</Label>
            <Input id="sm-start" type="number" value={startNumber} onChange={(e) => setStartNumber(e.target.value)} />
          </div>
          <Button onClick={() => void generate()} disabled={busy}>
            <Grid3x3 className="size-4" /> Generate
          </Button>
        </div>
      )}

      {zoneSeats.length === 0 ? (
        <p className="text-muted-foreground text-sm">No seats in this zone yet.</p>
      ) : (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <Badge variant="info" appearance="light" size="sm">{zoneSeats.length} seats</Badge>
            <span className="text-muted-foreground text-xs">Stage / front</span>
          </div>
          <div className="overflow-x-auto rounded-lg border border-border bg-muted/30 p-4">
            <div className="mx-auto mb-3 w-1/2 rounded bg-foreground/10 py-1 text-center text-[11px] uppercase tracking-wide text-muted-foreground">
              Stage
            </div>
            <div className="flex flex-col gap-1.5">
              {seatRows.map(([rowKey, rowSeats]) => (
                <div key={rowKey} className="flex items-center gap-1.5">
                  <span className="w-6 shrink-0 text-right text-xs text-muted-foreground">{rowKey}</span>
                  <div className="flex flex-wrap gap-1">
                    {rowSeats.map((s) => (
                      <span
                        key={s.id}
                        title={s.label}
                        className="inline-flex h-6 min-w-6 items-center justify-center rounded bg-primary/15 px-1 text-[10px] font-medium text-primary"
                      >
                        {s.number}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
