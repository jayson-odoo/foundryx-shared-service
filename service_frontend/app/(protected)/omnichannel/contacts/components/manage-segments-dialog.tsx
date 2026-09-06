'use client';

/**
 * "Manage segments" dialog (AC-CTM-06, amended 2026-09-06 review rounds 1+2)
 * - rename, edit filter, delete for the workspace's saved segments. Reuses
 * the SAME `FilterBuilder` the Filters button opens (seeded via
 * `initialValue`) so there is exactly one filter-tree editor in the system.
 *
 * Delete rides the CORE grace-window engine (`contact_segments.delete`,
 * `deferred_actions.py`) - no confirmation dialog (a hand-rolled destructive
 * `AlertDialog` here was a design-language hard-fail on review; every other
 * destructive action in this module already went through the deferred
 * engine). A toast-hosted countdown (`deferredToast`, the SAME affordance a
 * list row's "…" menu uses) replaces the confirm step - Cancel withdraws it
 * while the window is open.
 *
 * Review round 2: the delete controller (ONE `useDeferredAction`, one
 * countdown at a time) is now owned by the PAGE
 * (`use-segment-delete-controller.ts`), not this dialog - see that file's
 * header for why. This component only renders each segment as its own
 * `SegmentRow` and disables every row's Delete button except the one
 * actually counting down.
 */
import { useState } from 'react';
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
import type { FilterFieldDef } from '@/types/resource';
import type { ContactSegment } from '@/types/omnichannel';

export interface ManageSegmentsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  segments: ContactSegment[];
  filterFields: FilterFieldDef[];
  onRename: (id: string, name: string) => Promise<unknown>;
  onEditFilter: (id: string, filter: import('@/types/resource').FilterGroup | null) => Promise<unknown>;
  /** The segment currently parked for delete (from the page-level
   * `useSegmentDeleteController`) - every OTHER row's Delete button disables
   * while this is set (one countdown at a time). */
  deletingId: string | null;
  /** Starts the grace-window delete for a row - owned by the caller so the
   * countdown survives this dialog closing (review round 2, should-fix 4). */
  onDelete: (segment: ContactSegment) => void;
}

interface SegmentRowProps {
  segment: ContactSegment;
  filterFields: FilterFieldDef[];
  isDeleting: boolean;
  /** Another row's delete is counting down - THIS row's Delete disables too
   * (review round 2, blocker 2: one countdown at a time). */
  deleteDisabled: boolean;
  onRename: (segment: ContactSegment) => void;
  renaming: boolean;
  renameValue: string;
  onRenameValueChange: (value: string) => void;
  onRenameCommit: () => void;
  onRenameCancel: () => void;
  renameBusy: boolean;
  onEditFilter: (filter: import('@/types/resource').FilterGroup | null) => void;
  onDelete: () => void;
}

function SegmentRow({
  segment,
  filterFields,
  isDeleting,
  deleteDisabled,
  onRename,
  renaming,
  renameValue,
  onRenameValueChange,
  onRenameCommit,
  onRenameCancel,
  renameBusy,
  onEditFilter,
  onDelete,
}: SegmentRowProps) {
  return (
    <div
      data-pending={isDeleting ? 'true' : undefined}
      className="flex items-center gap-2 rounded-md border border-border p-2.5 data-[pending=true]:opacity-50"
    >
      {renaming ? (
        <Input
          autoFocus
          value={renameValue}
          onChange={(e) => onRenameValueChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') onRenameCommit();
            if (e.key === 'Escape') onRenameCancel();
          }}
          onBlur={onRenameCommit}
          disabled={renameBusy}
          className="h-8 flex-1"
        />
      ) : (
        <div className="flex flex-1 flex-col overflow-hidden">
          <ClampedText text={segment.name} lines={1} className="text-sm font-medium" />
          {segment.description && (
            <ClampedText text={segment.description} lines={1} className="text-xs text-muted-foreground" />
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
          <FilterBuilder fields={filterFields} initialValue={segment.filter} onApply={onEditFilter} />
        </PopoverContent>
      </Popover>

      <Button
        variant="ghost"
        size="sm"
        mode="icon"
        aria-label={`Rename ${segment.name}`}
        onClick={() => onRename(segment)}
        disabled={isDeleting}
      >
        <Pencil className="size-4" />
      </Button>
      <Button
        variant="ghost"
        size="sm"
        mode="icon"
        aria-label={`Delete ${segment.name}`}
        onClick={onDelete}
        disabled={deleteDisabled}
      >
        <Trash2 className="size-4 text-destructive" />
      </Button>
    </div>
  );
}

export function ManageSegmentsDialog({
  open,
  onOpenChange,
  segments,
  filterFields,
  onRename,
  onEditFilter,
  deletingId,
  onDelete,
}: ManageSegmentsDialogProps) {
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [busyId, setBusyId] = useState<string | null>(null);

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
              {segments.map((segment) => (
                <SegmentRow
                  key={segment.id}
                  segment={segment}
                  filterFields={filterFields}
                  isDeleting={deletingId === segment.id}
                  deleteDisabled={deletingId !== null}
                  renaming={renamingId === segment.id}
                  renameValue={renameValue}
                  renameBusy={busyId === segment.id}
                  onRename={startRename}
                  onRenameValueChange={setRenameValue}
                  onRenameCommit={() => void commitRename(segment.id)}
                  onRenameCancel={() => setRenamingId(null)}
                  onEditFilter={(g) => void onEditFilter(segment.id, g)}
                  onDelete={() => onDelete(segment)}
                />
              ))}
            </div>
          )}
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
