'use client';

import { useState } from 'react';
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
import { Textarea } from '@/components/ui/textarea';
import { MultiSelect } from '@/components/platform/multi-select';
import { personaService } from '@/services/persona-service';
import {
  usePersonaGrants,
  usePortalPermissions,
} from '@/hooks/use-personas';
import type { Persona } from '@/types/persona';

/**
 * Persona create/edit dialog (AC-06-26). Edit label/description + the portal-key
 * grant editor (a MultiSelect — search + select-all — over the portal-permission
 * catalog, saved via PUT /ems/personas/{id}/permissions). For a SYSTEM persona
 * the key is read-only (server-locked); the label stays editable. On create the
 * grant editor is hidden (grants attach after the persona exists).
 */
export function PersonaDialog({
  item,
  onClose,
  onSaved,
}: {
  item: Persona | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEdit = Boolean(item);
  const [key, setKey] = useState(item?.key ?? '');
  const [label, setLabel] = useState(item?.label ?? '');
  const [description, setDescription] = useState(item?.description ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const grants = usePersonaGrants(item?.id ?? '');

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      if (item) {
        await personaService.update(item.id, {
          // System persona key is locked — never send it.
          key: item.isSystem ? undefined : key.trim(),
          label: label.trim(),
          description,
        });
        await grants.save();
      } else {
        await personaService.create({
          key: key.trim(),
          label: label.trim() || key.trim(),
          description,
        });
      }
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save the persona.');
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{isEdit ? 'Edit persona' : 'New persona'}</DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="persona-key">Key *</Label>
            <Input
              id="persona-key"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              disabled={item?.isSystem}
              readOnly={item?.isSystem}
              autoFocus={!isEdit}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="persona-label">Label *</Label>
            <Input
              id="persona-label"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="persona-desc">Description</Label>
            <Textarea
              id="persona-desc"
              value={description ?? ''}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
            />
          </div>

          {isEdit && <GrantEditor grants={grants} />}

          {error && <p className="text-sm text-destructive">{error}</p>}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            onClick={() => void save()}
            disabled={busy || !key.trim() || !label.trim()}
          >
            {busy ? 'Saving…' : isEdit ? 'Save' : 'Create'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function GrantEditor({
  grants,
}: {
  grants: ReturnType<typeof usePersonaGrants>;
}) {
  const catalog = usePortalPermissions();
  return (
    <div className="space-y-1.5">
      <Label htmlFor="persona-grants">Portal access</Label>
      <MultiSelect
        placeholder="No portal access"
        searchPlaceholder="Search keys…"
        options={catalog.permissions.map((p) => ({
          label: p.label,
          value: p.key,
        }))}
        value={grants.keys}
        onChange={grants.setKeys}
      />
    </div>
  );
}
