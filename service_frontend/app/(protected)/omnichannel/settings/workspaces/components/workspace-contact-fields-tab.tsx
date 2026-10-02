'use client';

/**
 * Contact fields tab (plan 25, AC-CDM-31) - the workspace's custom-field
 * registry as an embedded ResourceList, mirroring the API-keys tab pattern.
 * Delete asks for confirmation naming the count of contacts holding a value
 * (a dynamic description the generic `ResourceAction.confirm` can't express,
 * so it's a small local AlertDialog instead - same shell primitive, custom copy).
 */
import { useCallback, useState } from 'react';
import { Info } from 'lucide-react';
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
import { Card, CardContent } from '@/components/ui/card';
import { ResourceList } from '@/components/platform/resource-list';
import { useContactFields } from '@/hooks/use-contact-fields';
import type { ContactField } from '@/types/omnichannel';
import { ContactFieldDialog } from './contact-field-dialog';
import { useContactFieldList } from './use-contact-field-list';

export function WorkspaceContactFieldsTab({
  workspaceId,
  creating,
}: {
  workspaceId: string | null;
  creating: boolean;
}) {
  const { fields, create, update, remove } = useContactFields(workspaceId);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingField, setEditingField] = useState<ContactField | null>(null);
  const [pendingDelete, setPendingDelete] = useState<ContactField | null>(null);

  const onAdd = useCallback(() => {
    setEditingField(null);
    setDialogOpen(true);
  }, []);
  const onEdit = useCallback((field: ContactField) => {
    setEditingField(field);
    setDialogOpen(true);
  }, []);

  const { config } = useContactFieldList({
    fields,
    onEdit,
    onDelete: setPendingDelete,
    onAdd,
  });

  const confirmDelete = () => {
    if (pendingDelete) void remove(pendingDelete.id);
  };

  if (creating || !workspaceId) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center gap-2 py-16 text-center">
          <Info className="size-8 text-muted-foreground" />
          <p className="text-sm font-medium">Save the workspace to manage contact fields.</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <ResourceList config={config} />
      <ContactFieldDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        field={editingField}
        onCreate={(values) =>
          create({
            key: values.key,
            label: values.label,
            description: values.description || null,
            type: values.type,
            options: values.type === 'list' ? values.options.filter((o) => o.trim()) : undefined,
            visibility: values.visibility,
          })
        }
        onUpdate={(id, values) =>
          update(id, {
            label: values.label,
            description: values.description || null,
            options: values.type === 'list' ? values.options.filter((o) => o.trim()) : undefined,
            visibility: values.visibility,
          })
        }
      />
      <AlertDialog open={!!pendingDelete} onOpenChange={(open) => !open && setPendingDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete &ldquo;{pendingDelete?.label}&rdquo;?</AlertDialogTitle>
            <AlertDialogDescription>
              {pendingDelete && pendingDelete.valuesCount > 0
                ? `${pendingDelete.valuesCount} contact${pendingDelete.valuesCount === 1 ? '' : 's'} in this workspace ${
                    pendingDelete.valuesCount === 1 ? 'holds' : 'hold'
                  } a value for this field - it will be removed along with the field.`
                : 'No contacts hold a value for this field yet.'}{' '}
              This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={confirmDelete}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
