'use client';

/**
 * The "Shared with me" drive (plan sprint-3/05 follow-up) - roots others shared
 * TO the current user, shown in the SAME right-pane look as the main Drive grid.
 * Opening any root navigates to its scoped view (`/documents/shared/{token}`),
 * which limits the user to exactly that file/folder subtree.
 */
import { File as FileIcon, Folder, Users } from 'lucide-react';
import type { SharedWithMeItem } from '@/types/documents';

export function SharedWithMeGrid({
  items,
  loading,
  onOpen,
}: {
  items: SharedWithMeItem[];
  loading: boolean;
  onOpen: (token: string) => void;
}) {
  if (loading) {
    return <p className="p-10 text-center text-sm text-muted-foreground">Loading…</p>;
  }
  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 p-16 text-center">
        <Users className="size-8 text-muted-foreground" />
        <p className="text-sm font-medium">Nothing shared with you yet</p>
        <p className="text-xs text-muted-foreground">
          Files and folders other people share with you appear here.
        </p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-2 p-3 sm:grid-cols-3 lg:grid-cols-4">
      {items.map((item) => (
        <button
          key={item.token}
          type="button"
          onClick={() => onOpen(item.token)}
          className="flex flex-col gap-2 rounded-lg border bg-card p-3 text-left hover:bg-muted/50"
          data-testid="shared-with-me-item"
        >
          <div className="flex min-w-0 items-center gap-2">
            {item.targetKind === 'folder' ? (
              <Folder className="size-5 shrink-0 text-primary" />
            ) : (
              <FileIcon className="size-5 shrink-0 text-muted-foreground" />
            )}
            <span className="truncate text-sm font-medium">{item.name}</span>
          </div>
          {item.ownerName && (
            <span className="truncate text-xs text-muted-foreground">Shared by {item.ownerName}</span>
          )}
        </button>
      ))}
    </div>
  );
}
