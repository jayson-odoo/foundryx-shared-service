'use client';

/** Offerings tab on the Event detail (sprint-4/05, Cluster D). Embedded Resource
 * list of this event's offerings + create/edit dialog (RESERVED offerings mint
 * seats from a venue's zones). Self-contained — takes the event's template
 * roles/segments for the grants pickers. */
import { useCallback, useMemo, useState } from 'react';
import { ResourceList } from '@/components/platform/resource-list';
import type { TemplateChild } from '@/types/ems';
import type { Offering } from '@/types/registration';
import { useOfferingsListConfig } from './use-offerings-list-config';
import { OfferingFormDialog } from './offering-form-dialog';
import { SeatAllocationDialog } from './seat-allocation';

export function OfferingsTab({
  projectId,
  roles,
  segments,
}: {
  projectId: string;
  roles: TemplateChild[];
  segments: TemplateChild[];
}) {
  const [nonce, setNonce] = useState(0);
  const [creating, setCreating] = useState(false);
  const [editRow, setEditRow] = useState<Offering | null>(null);
  const [seatsRow, setSeatsRow] = useState<Offering | null>(null);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  const onCreate = useCallback(() => setCreating(true), []);
  const onEdit = useCallback((row: Offering) => setEditRow(row), []);
  const onViewSeats = useCallback((row: Offering) => setSeatsRow(row), []);

  const ctx = useMemo(
    () => ({ projectId, onCreate, onEdit, onViewSeats }),
    [projectId, onCreate, onEdit, onViewSeats],
  );
  const config = useOfferingsListConfig(ctx);

  return (
    <>
      <ResourceList key={nonce} config={config} />
      {creating && (
        <OfferingFormDialog
          projectId={projectId}
          offering={null}
          roles={roles}
          segments={segments}
          onClose={() => setCreating(false)}
          onSaved={() => { setCreating(false); reload(); }}
        />
      )}
      {editRow && (
        <OfferingFormDialog
          projectId={projectId}
          offering={editRow}
          roles={roles}
          segments={segments}
          onClose={() => setEditRow(null)}
          onSaved={() => { setEditRow(null); reload(); }}
        />
      )}
      {seatsRow && (
        <SeatAllocationDialog offering={seatsRow} onClose={() => setSeatsRow(null)} />
      )}
    </>
  );
}
