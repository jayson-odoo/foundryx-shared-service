'use client';

/**
 * "Manage segments" dialog (AC-CTM-06, amended 2026-09-06 review round 1) -
 * rename, edit filter, delete for the workspace's saved segments. Reuses the
 * SAME `FilterBuilder` the Filters button opens (seeded via `initialValue`)
 * so there is exactly one filter-tree editor in the system.
 *
 * Delete rides the CORE grace-window engine (`contact_segments.delete`,
 * `deferred_actions.py`) - no confirmation dialog (a hand-rolled destructive
 * `AlertDialog` here was a design-language hard-fail on review; every other
 * destructive action in this module already went through the deferred
 * engine). `useDeferredAction` parks the delete server-side and a toast-
 * hosted countdown (`deferredToast`, the SAME affordance a list row's "…"
 * menu uses) replaces the confirm step - Cancel withdraws it while the
 * window is open.
 */
import { useRef, useState } from 'react';
import { Filter, Pencil, Trash2 } from 'lucide-react';
import { toast } from '@/lib/toast';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { ApiError } from '@/lib/api-client';
import { ClampedText } from '@/components/platform/clamped-text';
import { FilterBuilder } from '@/components/platform/resource-list/filter-builder';
import { deferredToast, dismissDeferredToast } from '@/components/platform/resource-actions/deferred-toast';
import { useDeferredAction } from '@/hooks/use-deferred-action';
import { deferredDoneMessage, presentContinuous } from '@/lib/deferred-verb';
import type { FilterFieldDef } from '@/types/resource';
import type { ContactSegment } from '@/types/omnichannel';

export interface ManageSegmentsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  segments: ContactSegment[];
  filterFields: FilterFieldDef[];
  onRename: (id: string, name: string) => Promise<unknown>;
  onEditFilter: (id: string, filter: import('@/types/resource').FilterGroup | null) => Promise<unknown>;
  /** Called once the grace-window delete actually commits server-side - the
   * dialog owns the whole park/cancel/commit lifecycle itself, the caller
   * only needs to refresh its own segment list. */
  onDeleted?: () => void;
}

const DELETE_LABEL = 'Delete';
const ENTITY_TYPE = 'contact_segment';

function toastIdFor(segmentId: string): string {
  return `contact-segment-delete-${segmentId}`;
}

export function ManageSegmentsDialog({
  open,
  onOpenChange,
  segments,
  filterFields,
  onRename,
  onEditFilter,
  onDeleted,
}: ManageSegmentsDialogProps) {
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [busyId, setBusyId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  // Read from callbacks that outlive any single render (mirrors ActionMenu's
  // own `activeRef` - `deletingId` state would otherwise be a stale closure
  // inside `useDeferredAction`'s commit/fail/cancel handlers).
  const activeRef = useRef<{ id: string } | null>(null);

  const startRename = (segment: ContactSegment) => {
    setRenamingId(segment.id);
    setRenameValue(segment.name);
  };

  const commitRename = async (id: string) => {
    const name = renameValue.trim();
    if (!name) {
      setRenamingId(null);
      return;
    }
    setBusyId(id);
    try {
      await onRename(id, name);
      setRenamingId(null);
    } catch (error) {
      toast.error(
        error instanceof ApiError
          ? error.message
          : error instanceof Error
            ? error.message
            : 'Could not rename the segment.',
      );
    } finally {
      setBusyId(null);
    }
  };

  const settleDelete = () => {
    const active = activeRef.current;
    activeRef.current = null;
    if (active) dismissDeferredToast(toastIdFor(active.id));
    setDeletingId(null);
  };

  const deferred = useDeferredAction({
    onCommitted: () => {
      settleDelete();
      toast.success(deferredDoneMessage(DELETE_LABEL, ENTITY_TYPE, 1));
      onDeleted?.();
    },
    onFailed: (error) => {
      settleDelete();
      toast.error(error || 'Could not delete the segment.');
    },
    onCancelledElsewhere: settleDelete,
  });

  const handleDelete = async (segment: ContactSegment) => {
    setDeletingId(segment.id);
    try {
      const { commitAt, windowSeconds } = await deferred.start('contact_segments.delete', {
        entityType: ENTITY_TYPE,
        entityId: segment.id,
      });
      activeRef.current = { id: segment.id };
      deferredToast({
        id: toastIdFor(segment.id),
        verb: presentContinuous(DELETE_LABEL),
        commitAt,
        windowSeconds,
        onCancel: () => {
          void deferred.cancel();
          settleDelete();
        },
      });
    } catch (error) {
      setDeletingId(null);
      toast.error(error instanceof Error ? error.message : 'Could not delete the segment.');
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Manage segments</DialogTitle>
        </DialogHeader>
        <DialogBody>
          {segments.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">No saved segments yet.</p>
          ) : (
            <div className="flex max-h-[50vh] flex-col gap-2 overflow-y-auto">
              {segments.map((segment) => {
                const isDeleting = deletingId === segment.id;
                return (
                  <div
                    key={segment.id}
                    data-pending={isDeleting ? 'true' : undefined}
                    className="flex items-center gap-2 rounded-md border border-border p-2.5 data-[pending=true]:opacity-50"
                  >
                    {renamingId === segment.id ? (
                      <Input
                        autoFocus
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') void commitRename(segment.id);
                          if (e.key === 'Escape') setRenamingId(null);
                        }}
                        onBlur={() => void commitRename(segment.id)}
                        disabled={busyId === segment.id}
                        className="h-8 flex-1"
                      />
                    ) : (
                      <div className="flex flex-1 flex-col overflow-hidden">
                        <ClampedText text={segment.name} lines={1} className="text-sm font-medium" />
                        {segment.description && (
                          <ClampedText
                            text={segment.description}
                            lines={1}
                            className="text-xs text-muted-foreground"
                          />
                        )}
                      </div>
                    )}

                    <Popover>
                      <PopoverTrigger asChild>
                        <Button
                          variant="ghost"
                          size="sm"
                          mode="icon"
                          aria-label={`Edit ${segment.name} filter`}
                          disabled={isDeleting}
                        >
                          <Filter className="size-4" />
                        </Button>
                      </PopoverTrigger>
                      <PopoverContent align="end" className="w-auto p-3">
                        <FilterBuilder
                          fields={filterFields}
                          initialValue={segment.filter}
                          onApply={(g) => void onEditFilter(segment.id, g)}
                        />
                      </PopoverContent>
                    </Popover>

                    <Button
                      variant="ghost"
                      size="sm"
                      mode="icon"
                      aria-label={`Rename ${segment.name}`}
                      onClick={() => startRename(segment)}
                      disabled={isDeleting}
                    >
                      <Pencil className="size-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      mode="icon"
                      aria-label={`Delete ${segment.name}`}
                      onClick={() => void handleDelete(segment)}
                      disabled={isDeleting}
                    >
                      <Trash2 className="size-4 text-destructive" />
                    </Button>
                  </div>
                );
              })}
            </div>
          )}
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
