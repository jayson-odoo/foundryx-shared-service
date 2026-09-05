'use client';

/**
 * Status drawer (sprint-2/01) - create/edit a status node: label, color,
 * trait flags. System rows keep label/color editable but lock behavior flags
 * and delete. Delete offers deactivate + migrate-records when referenced.
 */
import { useEffect, useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { SearchSelect } from '@/components/platform/search-select';
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { Switch } from '@/components/ui/switch';
import { cn } from '@/lib/utils';
import { colorToHex, STATUS_COLOR_SWATCHES } from '@/components/platform/status-badge';
import type { StatusFlags, StatusNodeData } from '@/types/status-engine';

interface FlagField {
  key: keyof StatusFlags;
  label: string;
  hint: string;
}

const FLAG_FIELDS: FlagField[] = [
  { key: 'isInitial', label: 'Initial', hint: 'Records of this entity start here' },
  { key: 'isDefault', label: 'Default', hint: 'Pre-selected for new records' },
  { key: 'isTerminal', label: 'Terminal', hint: 'No outgoing transitions allowed' },
  { key: 'blocksAccess', label: 'Blocks access', hint: 'Sign-in/requests blocked while held' },
  { key: 'isArchived', label: 'Archived', hint: 'Hidden from the default list view' },
];

export interface StatusDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** null = create mode. */
  status: StatusNodeData | null;
  statuses: StatusNodeData[];
  canManage: boolean;
  onCreate: (label: string, color: string, flags: StatusFlags) => Promise<boolean>;
  onUpdate: (id: string, label: string, color: string, flags: StatusFlags) => Promise<boolean>;
  onDelete: (id: string) => Promise<boolean>;
  onSetActive: (id: string, active: boolean) => Promise<boolean>;
  onMigrate: (id: string, toStatusId: string) => Promise<boolean>;
}

export function StatusDrawer({
  open,
  onOpenChange,
  status,
  statuses,
  canManage,
  onCreate,
  onUpdate,
  onDelete,
  onSetActive,
  onMigrate,
}: StatusDrawerProps) {
  const [label, setLabel] = useState('');
  const [color, setColor] = useState<string>('gray');
  const [flags, setFlags] = useState<StatusFlags>({});
  const [migrateTo, setMigrateTo] = useState<string>('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setLabel(status?.label ?? '');
    // The picker always works in hex; stored legacy names map over.
    setColor(colorToHex(status?.color ?? '#6B7280'));
    setFlags(
      status
        ? {
            isInitial: status.isInitial,
            isDefault: status.isDefault,
            isTerminal: status.isTerminal,
            blocksAccess: status.blocksAccess,
            isArchived: status.isArchived,
          }
        : {},
    );
    setMigrateTo('');
    setError(null);
  }, [open, status]);

  const migrateTargets = useMemo(
    () => statuses.filter((s) => s.id !== status?.id && s.isActive),
    [statuses, status],
  );

  const save = async () => {
    if (!label.trim()) {
      setError('Label is required.');
      return;
    }
    setError(null);
    setSaving(true);
    const ok = status
      ? await onUpdate(status.id, label, color, status.isSystem ? {} : flags)
      : await onCreate(label, color, flags);
    setSaving(false);
    if (ok) onOpenChange(false);
  };

  const readOnly = !canManage;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex flex-col sm:max-w-md">
        <SheetHeader>
          <SheetTitle>{status ? `Edit status - ${status.label}` : 'New status'}</SheetTitle>
        </SheetHeader>
        {/* Scrollable body + pinned footer. */}
        <SheetBody className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto">
          <div className="flex flex-col gap-2">
            <Label htmlFor="status-label">
              Label <span className="text-destructive">*</span>
            </Label>
            <Input
              id="status-label"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="e.g. Pending Review"
              disabled={readOnly}
            />
            {error && <p className="text-xs text-destructive">{error}</p>}
          </div>

          <div className="flex flex-col gap-2">
            <Label>Color</Label>
            {/* Quick picks from the system tokens + a full picker for anything else. */}
            <div className="flex flex-wrap items-center gap-2">
              {STATUS_COLOR_SWATCHES.map((swatch) => (
                <button
                  key={swatch.hex}
                  type="button"
                  title={swatch.label}
                  aria-label={`Color ${swatch.label}`}
                  disabled={readOnly}
                  onClick={() => setColor(swatch.hex)}
                  className={cn(
                    PRESSED_CLASS,
                    'size-7 rounded-full border transition-shadow',
                    color.toLowerCase() === swatch.hex.toLowerCase()
                      ? 'border-primary ring-2 ring-primary/40'
                      : 'border-border hover:ring-2 hover:ring-muted-foreground/20',
                  )}
                  style={{ backgroundColor: swatch.hex }}
                />
              ))}
              <label
                className={cn(
                  'relative flex h-7 items-center gap-1.5 rounded-md border border-border px-2',
                  readOnly ? 'opacity-60' : 'cursor-pointer hover:bg-accent',
                )}
              >
                <span className="size-4 rounded-full border border-border" style={{ backgroundColor: color }} />
                <span className="font-mono text-xs text-muted-foreground uppercase">{color}</span>
                <input
                  type="color"
                  value={color}
                  disabled={readOnly}
                  onChange={(e) => setColor(e.target.value)}
                  aria-label="Custom color"
                  className="absolute inset-0 size-full cursor-pointer opacity-0 disabled:cursor-default"
                />
              </label>
            </div>
          </div>

          <Separator />
          <div className="flex flex-col gap-3.5">
            <div className="text-sm font-medium text-foreground">Behavior</div>
            {status?.isSystem && (
              <p className="text-xs text-muted-foreground">
                System status - behavior is locked; label, color and order stay editable.
              </p>
            )}
            {FLAG_FIELDS.map((field) => (
              <div key={field.key} className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm text-foreground">{field.label}</div>
                  <div className="text-xs text-muted-foreground">{field.hint}</div>
                </div>
                <Switch
                  checked={Boolean(flags[field.key])}
                  onCheckedChange={(checked) =>
                    setFlags((prev) => ({ ...prev, [field.key]: checked }))
                  }
                  disabled={readOnly || Boolean(status?.isSystem)}
                  aria-label={field.label}
                />
              </div>
            ))}
          </div>

          {status && (
            <>
              <Separator />
              <div className="flex flex-col gap-3">
                <div className="text-sm font-medium text-foreground">Records</div>
                <p className="text-xs text-muted-foreground">
                  {status.recordCount} record(s) currently hold this status. Hard delete is
                  blocked while referenced - deactivate it and migrate records instead.
                </p>
                {canManage && migrateTargets.length > 0 && (
                  <div className="flex items-center gap-2.5">
                    <SearchSelect
                      className="grow"
                      options={migrateTargets.map((t) => ({ value: t.id, label: t.label }))}
                      value={migrateTo}
                      onChange={setMigrateTo}
                      placeholder="Migrate records to…"
                      searchPlaceholder="Search statuses…"
                    />
                    <Button
                      variant="outline"
                      disabled={!migrateTo || status.recordCount === 0}
                      onClick={() => void onMigrate(status.id, migrateTo)}
                    >
                      Migrate
                    </Button>
                  </div>
                )}
              </div>
            </>
          )}
        </SheetBody>
        {canManage && (
          <div className="flex items-center justify-between gap-2.5 border-t border-border p-4">
            <div className="flex items-center gap-2.5">
              {status?.isSystem && (
                <p className="text-xs text-muted-foreground">
                  System status - cannot be deleted or deactivated (the seeded
                  lifecycle depends on it). Label and color stay yours.
                </p>
              )}
              {status && !status.isSystem && (
                <>
                  <Button
                    variant="outline"
                    onClick={() =>
                      void onSetActive(status.id, !status.isActive).then(
                        (ok) => ok && onOpenChange(false),
                      )
                    }
                  >
                    {status.isActive ? 'Deactivate' : 'Activate'}
                  </Button>
                  <Button
                    variant="destructive"
                    onClick={() =>
                      void onDelete(status.id).then((ok) => ok && onOpenChange(false))
                    }
                  >
                    Delete
                  </Button>
                </>
              )}
            </div>
            <Button onClick={() => void save()} disabled={saving}>
              {status ? 'Save status' : 'Create status'}
            </Button>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
