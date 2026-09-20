'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Play } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { SearchSelect } from '@/components/platform/search-select';
import { useAutocountCompany } from '@/hooks/use-autocount-company';
import { useBuildPullSnapshot } from '@/hooks/use-autocount-pull';
import type { AutocountCompany } from '@/types/autocount';
import { acPullSnapshotHref, entityLabel, isPullCapable } from '../../components/autocount-meta';

export interface BuildSnapshotDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  companies: AutocountCompany[];
  onBuilt: () => void;
}

/**
 * Build-snapshot dialog (AC-10-37/50) - operator-triggered build against a
 * company + entity, `requestedVia: 'operator'`. Re-attaches to an in-flight
 * build for the same pair (AC-10-26) rather than starting a second one -
 * the service call handles that, this dialog just navigates to the result.
 */
export function BuildSnapshotDialog({ open, onOpenChange, companies, onBuilt }: BuildSnapshotDialogProps) {
  const router = useRouter();
  const { building, error, build, reset } = useBuildPullSnapshot();
  const [companyId, setCompanyId] = useState('');
  const [entityType, setEntityType] = useState('');
  // The selected company's OWN entities - the entity picker offers only the
  // ones actually enabled for pull on THIS company (review round 1 item 2:
  // foolproof-UI, never offer an entity the build would 409 PULL_NOT_ENABLED
  // for). `companyId` starts blank; the hook harmlessly no-ops until picked.
  const { detail } = useAutocountCompany(companyId);

  useEffect(() => {
    if (!open) {
      setCompanyId('');
      setEntityType('');
      reset();
    }
  }, [open, reset]);

  // Picking a different company invalidates the previous entity pick - the
  // two pull-capable entities are not the same set across every company.
  useEffect(() => {
    setEntityType('');
  }, [companyId]);

  // Only companies with a Sorento company code can be pulled from
  // (AC-10-11) - foolproof-UI: never offer a company that would 422.
  const companyOptions = companies
    .filter((c) => Boolean(c.sorentoCompanyCode?.trim()))
    .map((c) => ({ label: c.name, value: c.id }));
  // Pull-CAPABLE entities only (`product`/`stock_balance`, never a plain
  // push master like `supplier`), in `pull` mode OR currently `active`
  // (browser round 1 fix, AC-10-38/48): a pull-capable book that already
  // flipped back to automatic push still needs to be pickable so the
  // operator can SEE the A6 `PUSH_ACTIVE` 409 rather than the option
  // silently vanishing - a non-pull-capable entity stays excluded
  // regardless of status (review round 1 item 2's original guard).
  const entityOptions = useMemo(
    () =>
      (detail?.entities ?? [])
        .filter((e) => isPullCapable(e.entityType) && (e.deliveryMode === 'pull' || e.etlStatus === 'active'))
        .map((e) => ({ label: entityLabel(e.entityType), value: e.entityType })),
    [detail?.entities],
  );

  async function submit() {
    const snapshot = await build(companyId, entityType);
    if (snapshot) {
      onBuilt();
      onOpenChange(false);
      router.push(acPullSnapshotHref(snapshot.id));
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Build snapshot</DialogTitle>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label>Company</Label>
            <SearchSelect
              options={companyOptions}
              value={companyId}
              onChange={setCompanyId}
              placeholder="Pick a company"
              ariaLabel="Company"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>Entity</Label>
            <SearchSelect
              options={entityOptions}
              value={entityType}
              onChange={setEntityType}
              placeholder="Pick an entity"
              ariaLabel="Entity"
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={building}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => void submit()} disabled={building || !companyId || !entityType}>
            <Play className="size-4" />
            Build
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
