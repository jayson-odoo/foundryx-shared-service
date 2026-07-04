'use client';

import { useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { Archive, ArchiveRestore, CloudOff, CloudUpload, Pencil, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import type { ResourceAction } from '@/components/platform/resource-list';
import { FormPublishError, formService } from '@/services/form-service';
import type { FormRow } from '@/types/forms';
import { formPath } from './paths';

const publishable = (f: FormRow) => f.currentVersionNumber == null || f.hasUnpublishedChanges;

/** ONE action registry — row `…`, bulk dropdown and form `…` share it
 * (workflow-list parity, D18). Visibility branches on Active vs Archived. */
export function useFormActions(): ResourceAction<FormRow>[] {
  const router = useRouter();

  return useMemo<ResourceAction<FormRow>[]>(
    () => [
      {
        id: 'edit',
        label: 'Edit',
        icon: Pencil,
        surfaces: { row: true },
        permission: 'forms.manage',
        isVisible: (rows) => rows.every((f) => !f.isTrashed),
        run: ([f]) => router.push(`${formPath(f.id)}?edit=1`),
      },
      {
        id: 'publish',
        label: 'Publish',
        icon: CloudUpload,
        surfaces: { row: true, bulk: true },
        permission: 'forms.manage',
        isVisible: (rows) => rows.length > 0 && rows.every((f) => !f.isTrashed && publishable(f)),
        run: async (rows, runtime) => {
          let published = 0;
          for (const f of rows) {
            try {
              await formService.publish(f.id);
              published += 1;
            } catch (e) {
              toast.error(
                e instanceof FormPublishError
                  ? `"${f.name}": ${e.problems[0]}`
                  : `"${f.name}" could not be published.`,
              );
            }
          }
          if (published) toast.success(`Published ${published} form${published === 1 ? '' : 's'}.`);
          runtime.reload();
        },
      },
      {
        id: 'unpublish',
        label: 'Unpublish',
        icon: CloudOff,
        surfaces: { row: true, bulk: true },
        permission: 'forms.manage',
        isVisible: (rows) =>
          rows.length > 0 && rows.every((f) => !f.isTrashed && f.status === 'published'),
        run: async (rows, runtime) => {
          for (const f of rows) await formService.unpublish(f.id);
          toast.success(`Unpublished ${rows.length} form${rows.length === 1 ? '' : 's'}.`);
          runtime.reload();
        },
      },
      {
        id: 'archive',
        label: 'Archive',
        icon: Archive,
        surfaces: { row: true, bulk: true, form: true },
        permission: 'forms.manage',
        isVisible: (rows) => rows.length > 0 && rows.every((f) => !f.isTrashed),
        run: async (rows, runtime) => {
          for (const f of rows) await formService.archive(f.id);
          toast.success(`Archived ${rows.length} form${rows.length === 1 ? '' : 's'}.`);
          runtime.reload();
        },
      },
      {
        id: 'restore',
        label: 'Restore',
        icon: ArchiveRestore,
        surfaces: { row: true, bulk: true },
        permission: 'forms.manage',
        isVisible: (rows) => rows.length > 0 && rows.every((f) => f.isTrashed),
        run: async (rows, runtime) => {
          for (const f of rows) await formService.restore(f.id);
          toast.success(`Restored ${rows.length} form${rows.length === 1 ? '' : 's'}.`);
          runtime.reload();
        },
      },
      {
        id: 'delete',
        label: 'Delete permanently',
        icon: Trash2,
        tone: 'destructive',
        surfaces: { row: true, bulk: true },
        permission: 'forms.manage',
        // Hard delete only from the Archived view (two-step safety) — drops
        // versions, submissions AND the form's scoped status graph (D4).
        isVisible: (rows) => rows.length > 0 && rows.every((f) => f.isTrashed),
        confirm: {
          title: 'Delete permanently?',
          description:
            'The form, its versions, its submissions and its submission pipeline are removed for good. This cannot be undone.',
          confirmLabel: 'Delete',
        },
        run: async (rows, runtime) => {
          for (const f of rows) await formService.remove(f.id);
          toast.success(`Deleted ${rows.length} form${rows.length === 1 ? '' : 's'}.`);
          runtime.reload();
        },
      },
    ],
    [router],
  );
}
