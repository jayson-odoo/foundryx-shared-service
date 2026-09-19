'use client';

import { useEffect, useState } from 'react';
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
import { useBuildPullSnapshot } from '@/hooks/use-autocount-pull';
import type { AutocountCompany } from '@/types/autocount';
import { AC_PULL_CAPABLE_ENTITY_TYPES, acPullSnapshotHref, entityLabel } from '../../components/autocount-meta';

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

  useEffect(() => {
    if (!open) {
      setCompanyId('');
      setEntityType('');
      reset();
    }
  }, [open, reset]);

  // Only companies with a Sorento company code can be pulled from
  // (AC-10-11) - foolproof-UI: never offer a company that would 422.
  const companyOptions = companies
    .filter((c) => Boolean(c.sorentoCompanyCode?.trim()))
    .map((c) => ({ label: c.name, value: c.id }));
  const entityOptions = AC_PULL_CAPABLE_ENTITY_TYPES.map((e) => ({ label: entityLabel(e), value: e }));

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
