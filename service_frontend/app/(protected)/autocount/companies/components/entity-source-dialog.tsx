'use client';

import { useEffect, useState } from 'react';
import { LoaderCircleIcon, TriangleAlert } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Alert, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { Label } from '@/components/ui/label';
import { SearchSelect } from '@/components/platform/search-select';
import type { AutocountEntityConfig, AutocountSourceImpl } from '@/types/autocount';
import {
  AC_API_CAPABLE_ENTITY_TYPES,
  AC_SOURCE_IMPL_OPTIONS,
  entityLabel,
  sourceImplLabel,
} from '../../components/autocount-meta';

function asSourceImpl(value: string): AutocountSourceImpl {
  return value === 'sql_db' ? 'sql_db' : 'autocount_read';
}

export interface EntitySourceDialogProps {
  entity: AutocountEntityConfig | null;
  onClose: () => void;
  onSave: (entityType: string, sourceImpl: AutocountSourceImpl) => Promise<void>;
}

/**
 * Switch an entity between the AutoCount API and a direct database task (plan
 * 22 S2, AC-22-08). A GUARDED act, not an inline toggle: it changes how every
 * later sync runs, so the picker sits behind an explicit confirm that states
 * the consequence for the chosen source, and the button reads as the switch.
 */
export function EntitySourceDialog({ entity, onClose, onSave }: EntitySourceDialogProps) {
  const [value, setValue] = useState<AutocountSourceImpl>('autocount_read');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (entity) setValue(asSourceImpl(entity.sourceImpl));
  }, [entity]);

  const current = entity ? asSourceImpl(entity.sourceImpl) : 'autocount_read';
  const changed = Boolean(entity) && value !== current;
  // Foolproof-UI: an entity with no confirmed AutoCount API payload (plan 22
  // S4's masters fan-out) offers ONE valid option, never a guaranteed-to-fail
  // switch the backend would refuse anyway (`CompanyService.update_entity_config`).
  const apiCapable = entity !== null && AC_API_CAPABLE_ENTITY_TYPES.includes(entity.entityType);
  const sourceOptions = apiCapable
    ? AC_SOURCE_IMPL_OPTIONS
    : AC_SOURCE_IMPL_OPTIONS.filter((o) => o.value === 'sql_db');

  async function submit() {
    if (!entity || !changed) return;
    setSaving(true);
    try {
      await onSave(entity.entityType, value);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={Boolean(entity)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Source{entity ? ` - ${entityLabel(entity.entityType)}` : ''}</DialogTitle>
          <DialogDescription>Where this entity&apos;s records are read from.</DialogDescription>
        </DialogHeader>
        <DialogBody>
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-2">
              <Label>Source</Label>
              <SearchSelect
                options={sourceOptions}
                value={value}
                onChange={(v) => setValue(asSourceImpl(v))}
                ariaLabel="Entity source"
              />
            </div>
            {changed && (
              <Alert variant="warning" appearance="light" data-testid="source-switch-warning">
                <AlertIcon>
                  <TriangleAlert />
                </AlertIcon>
                <AlertTitle>
                  {value === 'sql_db'
                    ? 'Syncs will run from the database task once it is activated.'
                    : 'Syncs return to the AutoCount API; an active database task is paused.'}
                </AlertTitle>
              </Alert>
            )}
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={!changed || saving} data-testid="save-source">
            {saving && <LoaderCircleIcon className="size-4 animate-spin" />}
            Switch to {sourceImplLabel(value)}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
