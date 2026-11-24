'use client';

/**
 * Client apps settings (the consumer app that owns a tenant's workspaces and
 * partner keys - client app -> workspaces -> channels). List, create, rename,
 * and move a workspace between client apps. Gated by `partner_keys.manage`,
 * the same permission as the partner-key routes.
 */
import { Fragment, useEffect, useRef, useState } from 'react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { ResourceList } from '@/components/platform/resource-list';
import { useClientApps } from '@/hooks/use-client-apps';
import type { ClientApp, ClientAppWorkspace } from '@/types/omnichannel';
import { ClientAppDialog } from './components/client-app-dialog';
import { ClientAppWorkspacesDialog } from './components/client-app-workspaces-dialog';
import { MoveWorkspaceDialog } from './components/move-workspace-dialog';
import { useClientAppList } from './components/use-client-app-list';

function ClientAppsView() {
  const { apps, error, create, rename, moveWorkspace } = useClientApps();

  // Remount the ResourceList whenever the underlying data changes (initial
  // load + after each mutation) so the client-side fetcher re-pages over
  // fresh data - mirrors the quick-replies settings screen.
  const [version, setVersion] = useState(0);
  const prevApps = useRef(apps);
  useEffect(() => {
    if (prevApps.current !== apps) {
      prevApps.current = apps;
      setVersion((v) => v + 1);
    }
  }, [apps]);

  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [editingApp, setEditingApp] = useState<ClientApp | null>(null);

  const [workspacesDialogOpen, setWorkspacesDialogOpen] = useState(false);
  const [workspacesApp, setWorkspacesApp] = useState<ClientApp | null>(null);

  const [moveDialogOpen, setMoveDialogOpen] = useState(false);
  const [movingWorkspace, setMovingWorkspace] = useState<ClientAppWorkspace | null>(null);

  const config = useClientAppList({
    apps,
    onRename: (app) => {
      setEditingApp(app);
      setEditDialogOpen(true);
    },
    onViewWorkspaces: (app) => {
      setWorkspacesApp(app);
      setWorkspacesDialogOpen(true);
    },
    onAdd: () => {
      setEditingApp(null);
      setEditDialogOpen(true);
    },
  }).config;

  if (error && apps.length === 0) {
    return <p className="text-sm text-destructive">{error}</p>;
  }

  return (
    <Fragment>
      <ResourceList key={version} config={config} />
      <ClientAppDialog
        open={editDialogOpen}
        onOpenChange={setEditDialogOpen}
        app={editingApp}
        onCreate={(values) => create(values)}
        onRename={(id, values) => rename(id, values)}
      />
      <ClientAppWorkspacesDialog
        open={workspacesDialogOpen}
        onOpenChange={setWorkspacesDialogOpen}
        app={apps.find((a) => a.id === workspacesApp?.id) ?? workspacesApp}
        onMove={(ws) => {
          setMovingWorkspace(ws);
          setMoveDialogOpen(true);
        }}
      />
      <MoveWorkspaceDialog
        open={moveDialogOpen}
        onOpenChange={setMoveDialogOpen}
        workspace={movingWorkspace}
        fromClientAppId={workspacesApp?.id ?? null}
        apps={apps}
        onMove={(targetClientAppId, workspaceId) => moveWorkspace(targetClientAppId, workspaceId)}
      />
    </Fragment>
  );
}

export default function ClientAppsPage() {
  return (
    <RequirePermission permission="partner_keys.manage">
      <Fragment>
        <Container width="fluid">
          <ClientAppsView />
        </Container>
      </Fragment>
    </RequirePermission>
  );
}
