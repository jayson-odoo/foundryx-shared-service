'use client';

import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import {
  Toolbar,
  ToolbarDescription,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { ResourceList } from '@/components/platform/resource-list';
import { RequirePermission } from '@/components/common/require-permission';
import { useQuickReplies } from '@/hooks/use-quick-replies';
import { workspaceService } from '@/services/workspace-service';
import type { QuickReply } from '@/types/omnichannel';
import type {
  QuickReplyCreateInput,
  QuickReplyUpdateInput,
} from '@/services/quick-reply-service';
import { useQuickRepliesListConfig } from './use-quick-replies-list-config';
import { QuickReplyDialog } from './quick-reply-dialog';

/**
 * Quick-replies settings (plan sprint-3/12) - canned responses the inbox
 * composer's ★ picker consumes, on the config-driven Resource shell. Gated by
 * `workspaces.manage`. Workspace resolution mirrors the inbox host: the default
 * workspace, overridable with `?workspaceId=` (same contract as the media page).
 */
function QuickRepliesView() {
  // Resolve the workspace: ?workspaceId= override, else the default workspace.
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [resolving, setResolving] = useState(true);
  useEffect(() => {
    const override = new URLSearchParams(window.location.search).get('workspaceId');
    if (override) {
      setWorkspaceId(override);
      setResolving(false);
      return;
    }
    let active = true;
    workspaceService
      .list({ page: 0, pageSize: 50 })
      .then((res) => {
        if (!active) return;
        const ws = res.data.find((w) => w.isDefault) ?? res.data[0];
        setWorkspaceId(ws?.id ?? null);
      })
      .catch(() => active && setWorkspaceId(null))
      .finally(() => active && setResolving(false));
    return () => {
      active = false;
    };
  }, []);

  const { items, error, create, update, remove } = useQuickReplies(workspaceId);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<QuickReply | null>(null);

  // Remount the ResourceList whenever the underlying items change (initial load
  // + after each mutation) so the client-side fetcher re-pages over fresh data.
  const [version, setVersion] = useState(0);
  const prevItems = useRef(items);
  useEffect(() => {
    if (prevItems.current !== items) {
      prevItems.current = items;
      setVersion((v) => v + 1);
    }
  }, [items]);

  const handlers = useMemo(
    () => ({
      onCreate: () => {
        setEditing(null);
        setDialogOpen(true);
      },
      onEdit: (item: QuickReply) => {
        setEditing(item);
        setDialogOpen(true);
      },
      onDelete: async (item: QuickReply) => {
        try {
          await remove(item.id);
          toast.success('Quick reply deleted.');
        } catch (e) {
          toast.error(e instanceof Error ? e.message : 'Could not delete the quick reply.');
        }
      },
    }),
    [remove],
  );

  const config = useQuickRepliesListConfig(items, handlers);

  const handleCreate = async (input: QuickReplyCreateInput) => {
    await create(input);
    toast.success('Quick reply created.');
  };
  const handleUpdate = async (id: string, input: QuickReplyUpdateInput) => {
    await update(id, input);
    toast.success('Quick reply saved.');
  };

  if (!resolving && !workspaceId) {
    return (
      <p className="text-sm text-muted-foreground">
        No workspace is available. Create a workspace first.
      </p>
    );
  }
  if (error && items.length === 0) {
    return <p className="text-sm text-destructive">{error}</p>;
  }

  return (
    <Fragment>
      <ResourceList key={version} config={config} />
      {dialogOpen && (
        <QuickReplyDialog
          item={editing}
          onClose={() => setDialogOpen(false)}
          onCreate={handleCreate}
          onUpdate={handleUpdate}
        />
      )}
    </Fragment>
  );
}

export default function QuickRepliesPage() {
  return (
    <RequirePermission permission="workspaces.manage">
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle />
              <ToolbarDescription>
                Canned responses agents insert from the inbox composer.
              </ToolbarDescription>
            </ToolbarHeading>
          </Toolbar>
        </Container>
        <Container width="fluid">
          <QuickRepliesView />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}
