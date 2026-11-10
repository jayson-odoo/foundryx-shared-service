'use client';

/**
 * Tags tab (plan 25, AC-CDM-32) - the workspace's tag registry as an embedded
 * ResourceList. Delete asks for confirmation naming the attached-contacts
 * count (same dynamic-copy pattern as the Contact fields tab).
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
import { useContactTags } from '@/hooks/use-contact-tags';
import type { ContactTag } from '@/types/omnichannel';
import { ContactTagDialog } from './contact-tag-dialog';
import { useContactTagList } from './use-contact-tag-list';

export function WorkspaceTagsTab({ workspaceId, creating }: { workspaceId: string | null; creating: boolean }) {
  const { tags, create, update, remove } = useContactTags(workspaceId);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingTag, setEditingTag] = useState<ContactTag | null>(null);
  const [pendingDelete, setPendingDelete] = useState<ContactTag | null>(null);

  const onAdd = useCallback(() => {
    setEditingTag(null);
    setDialogOpen(true);
  }, []);
  const onEdit = useCallback((tag: ContactTag) => {
    setEditingTag(tag);
    setDialogOpen(true);
  }, []);

  const { config } = useContactTagList({ tags, onEdit, onDelete: setPendingDelete, onAdd });

  const confirmDelete = () => {
    if (pendingDelete) void remove(pendingDelete.id);
  };

  if (creating || !workspaceId) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center gap-2 py-16 text-center">
          <Info className="size-8 text-muted-foreground" />
          <p className="text-sm font-medium">Save the workspace to manage tags.</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <ResourceList config={config} />
      <ContactTagDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        tag={editingTag}
        onCreate={(values) =>
          create({
            name: values.name,
            emoji: values.emoji || null,
            color: values.color || null,
            description: values.description || null,
          })
        }
        onUpdate={(id, values) =>
          update(id, {
            name: values.name,
            emoji: values.emoji || null,
            color: values.color || null,
            description: values.description || null,
          })
        }
      />
      <AlertDialog open={!!pendingDelete} onOpenChange={(open) => !open && setPendingDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete &ldquo;{pendingDelete?.name}&rdquo;?</AlertDialogTitle>
            <AlertDialogDescription>
              {pendingDelete && pendingDelete.contactsCount > 0
                ? `${pendingDelete.contactsCount} contact${pendingDelete.contactsCount === 1 ? '' : 's'} ${
                    pendingDelete.contactsCount === 1 ? 'has' : 'have'
                  } this tag - it will be removed from ${pendingDelete.contactsCount === 1 ? 'them' : 'all of them'}.`
                : 'No contacts have this tag yet.'}{' '}
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
