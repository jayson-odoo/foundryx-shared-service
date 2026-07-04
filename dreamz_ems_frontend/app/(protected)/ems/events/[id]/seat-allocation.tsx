'use client';

/** Seat allocation view (sprint-4/05) — the cinema map for a RESERVED offering:
 * every minted capacity_unit as a chip coloured by status (free / held / sold),
 * grouped by zone → row. Click a seat to see its occupant. This is the static
 * allocation view; the LIVE held/sold WS map + countdown is slice 2. */
import { useEffect, useMemo, useState } from 'react';
import { LoaderCircleIcon } from 'lucide-react';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { registrationService } from '@/services/registration-service';
import { cn } from '@/lib/utils';
import type { CapacityUnit, Offering } from '@/types/registration';

const SEAT_STYLES: Record<CapacityUnit['status'], string> = {
  free: 'bg-success/15 text-success hover:bg-success/25',
  held: 'bg-warning/20 text-warning-foreground hover:bg-warning/30 ring-1 ring-warning/40',
  sold: 'bg-muted-foreground/20 text-foreground hover:bg-muted-foreground/30',
};

export function SeatAllocationDialog({
  offering,
  onClose,
}: {
  offering: Offering;
  onClose: () => void;
}) {
  const [units, setUnits] = useState<CapacityUnit[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<CapacityUnit | null>(null);

  useEffect(() => {
    registrationService
      .listCapacityUnits(offering.projectId, offering.id)
      .then(setUnits)
      .finally(() => setLoading(false));
  }, [offering.projectId, offering.id]);

  const counts = useMemo(
    () => ({
      free: units.filter((u) => u.status === 'free').length,
      held: units.filter((u) => u.status === 'held').length,
      sold: units.filter((u) => u.status === 'sold').length,
    }),
    [units],
  );

  // group by zone → row, ordered by seat geometry
  const grouped = useMemo(() => {
    const byZone = new Map<string, Map<string, CapacityUnit[]>>();
    for (const u of [...units].sort((a, b) => a.y - b.y || a.x - b.x)) {
      const zone = u.zone ?? '—';
      const row = u.row ?? String(u.y);
      if (!byZone.has(zone)) byZone.set(zone, new Map());
      const rows = byZone.get(zone)!;
      if (!rows.has(row)) rows.set(row, []);
      rows.get(row)!.push(u);
    }
    return Array.from(byZone.entries()).map(([zone, rows]) => ({ zone, rows: Array.from(rows.entries()) }));
  }, [units]);

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle>{offering.productName} — seat allocation</DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-4">
          {/* legend + counts */}
          <div className="flex flex-wrap items-center gap-4 text-sm">
            <Legend className={SEAT_STYLES.free} label={`Free (${counts.free})`} />
            <Legend className={SEAT_STYLES.held} label={`Held (${counts.held})`} />
            <Legend className={SEAT_STYLES.sold} label={`Sold (${counts.sold})`} />
            <span className="text-muted-foreground ms-auto">{units.length} seats total</span>
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-16 text-muted-foreground">
              <LoaderCircleIcon className="size-5 animate-spin" />
            </div>
          ) : units.length === 0 ? (
            <p className="text-muted-foreground py-8 text-center text-sm">
              No seats minted yet. Edit the offering → Mint seats.
            </p>
          ) : (
            <div className="max-h-[55vh] space-y-6 overflow-auto rounded-lg border border-border bg-muted/20 p-4">
              <div className="mx-auto w-1/2 rounded bg-foreground/10 py-1 text-center text-[11px] uppercase tracking-wide text-muted-foreground">
                Stage
              </div>
              {grouped.map(({ zone, rows }) => (
                <div key={zone} className="space-y-1.5">
                  <div className="text-xs font-medium text-muted-foreground">{zone}</div>
                  {rows.map(([row, rowSeats]) => (
                    <div key={row} className="flex items-center gap-1.5">
                      <span className="w-6 shrink-0 text-right text-xs text-muted-foreground">{row}</span>
                      <div className="flex flex-wrap gap-1">
                        {rowSeats.map((u) => (
                          <button
                            key={u.id}
                            type="button"
                            onClick={() => setSelected(u)}
                            title={`${u.label}${u.occupantName ? ` · ${u.occupantName}` : ' · free'}`}
                            className={cn(
                              'inline-flex h-7 min-w-7 items-center justify-center rounded px-1 text-[10px] font-medium transition-colors',
                              SEAT_STYLES[u.status],
                              selected?.id === u.id && 'ring-2 ring-primary',
                            )}
                          >
                            {u.number}
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}

          {/* occupant inspector */}
          {selected && (
            <div className="flex items-center justify-between rounded-lg border border-border bg-card px-4 py-3">
              <div className="flex items-center gap-3">
                <span className="font-medium">Seat {selected.label}</span>
                {selected.zone && <span className="text-muted-foreground text-sm">{selected.zone}</span>}
                {selected.status === 'sold' && <Badge variant="secondary" appearance="light" size="sm">Sold</Badge>}
                {selected.status === 'held' && <Badge variant="warning" appearance="light" size="sm">Held</Badge>}
                {selected.status === 'free' && <Badge variant="success" appearance="light" size="sm">Free</Badge>}
              </div>
              <span className="text-sm">
                {selected.occupantName ? (
                  <>Occupant: <span className="font-medium">{selected.occupantName}</span></>
                ) : (
                  <span className="text-muted-foreground">Vacant</span>
                )}
              </span>
            </div>
          )}
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}

function Legend({ className, label }: { className: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={cn('inline-block size-3.5 rounded', className)} />
      <span className="text-muted-foreground">{label}</span>
    </span>
  );
}
