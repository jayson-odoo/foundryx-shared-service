'use client';

/**
 * "Manage segments" dialog (AC-CTM-06) - rename, edit filter, delete (with
 * confirmation) for the workspace's saved segments. Reuses the SAME
 * `FilterBuilder` the Filters button opens (seeded via `initialValue`) so
 * there is exactly one filter-tree editor in the system.
 */
import { useState } from 'react';
import { Filter, Pencil, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
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
  onDelete: (id: string) => Promise<unknown>;
}

export function ManageSegmentsDialog({
  open,
  onOpenChange,
  segments,
  filterFields,
  onRename,
  onEditFilter,
  onDelete,
}: ManageSegmentsDialogProps) {
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [pendingDelete, setPendingDelete] = useState<ContactSegment | null>(null);
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

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    setBusyId(pendingDelete.id);
    try {
      await onDelete(pendingDelete.id);
      toast.success('Segment deleted.');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not delete the segment.');
    } finally {
      setBusyId(null);
      setPendingDelete(null);
    }
  };

  return (
    <>
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
                  <div
                    key={segment.id}
                    className="flex items-center gap-2 rounded-md border border-border p-2.5"
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
                        <span className="truncate text-sm font-medium">{segment.name}</span>
                        {segment.description && (
                          <span className="truncate text-xs text-muted-foreground">{segment.description}</span>
                        )}
                      </div>
                    )}

                    <Popover>
                      <PopoverTrigger asChild>
                        <Button variant="ghost" size="sm" mode="icon" aria-label={`Edit ${segment.name} filter`}>
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
                    >
                      <Pencil className="size-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      mode="icon"
                      aria-label={`Delete ${segment.name}`}
                      onClick={() => setPendingDelete(segment)}
                    >
                      <Trash2 className="size-4 text-destructive" />
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </DialogBody>
        </DialogContent>
      </Dialog>

      <AlertDialog open={!!pendingDelete} onOpenChange={(v) => !v && setPendingDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete &ldquo;{pendingDelete?.name}&rdquo;?</AlertDialogTitle>
            <AlertDialogDescription>This cannot be undone.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => void confirmDelete()}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
