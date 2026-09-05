'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm, type UseFormReturn } from 'react-hook-form';
import {
  FormInput,
  GitBranch,
  KeyRound,
  MessageCircle,
  Settings as SettingsIcon,
  Tag,
  Users as UsersIcon,
} from 'lucide-react';
import { toast } from 'sonner';
import type { ResourceFormConfig } from '@/components/platform/resource-form';
import type { LayoutController } from '@/components/platform/status-engine';
import { workspaceService } from '@/services/workspace-service';
import type { Workspace } from '@/types/omnichannel';
import { SettingsTab, ChannelsTab, MembersTab } from './workspace-form-fields';
import { ApiKeysTab } from './workspace-api-keys-tab';
import { WorkspaceLifecycleTab } from './workspace-lifecycle-tab';
import { WorkspaceContactFieldsTab } from './workspace-contact-fields-tab';
import { WorkspaceTagsTab } from './workspace-tags-tab';
import { useWorkspaceActions } from './use-workspace-actions';
import { useCan } from '@/hooks/use-can';
import { workspaceFormHref, workspaceFormPath, workspacesListPath } from './paths';
import { workspaceFormSchema, type WorkspaceFormValues } from './workspace-schema';

function toFormValues(ws: Workspace | null): WorkspaceFormValues {
  if (!ws) return { name: '', status: 'ACTIVE' };
  return { name: ws.name, status: ws.status };
}

export interface UseWorkspaceFormResult {
  config: ResourceFormConfig<Workspace> | null;
  form: UseFormReturn<WorkspaceFormValues>;
  isLoading: boolean;
  notFound: boolean;
}

export function useWorkspaceForm(
  workspaceId: string | undefined,
  initialEditing: boolean,
): UseWorkspaceFormResult {
  const router = useRouter();
  const actions = useWorkspaceActions();
  const { can } = useCan();
  const creating = !workspaceId;

  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  // Plan 25 - the Lifecycle tab's canvas layout draft plugs into this form's
  // Save/Cancel exactly like the form engine's Flow tab (BL-064 pattern).
  const [lifecycleDirty, setLifecycleDirty] = useState(false);
  const lifecycleLayoutController = useRef<LayoutController | null>(null);

  const form = useForm<WorkspaceFormValues>({
    resolver: zodResolver(workspaceFormSchema),
    defaultValues: toFormValues(null),
  });

  useEffect(() => {
    let active = true;
    if (creating) {
      setWorkspace(null);
      form.reset(toFormValues(null));
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    workspaceService
      .get(workspaceId)
      .then((ws) => {
        if (!active) return;
        setWorkspace(ws);
        form.reset(toFormValues(ws));
        setNotFound(false);
      })
      .catch(() => active && setNotFound(true))
      .finally(() => active && setIsLoading(false));
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId, creating]);

  const config = useMemo<ResourceFormConfig<Workspace> | null>(() => {
    if (isLoading || notFound) return null;

    const onSave = async (): Promise<boolean> => {
      let ok = false;
      await form.handleSubmit(async (values) => {
        if (creating) {
          const created = await workspaceService.create({
            name: values.name,
            status: values.status,
          });
          toast.success('Workspace created.');
          router.push(workspaceFormPath(created.id));
        } else {
          const updated = await workspaceService.update(workspaceId, {
            name: values.name,
            status: values.status,
          });
          setWorkspace(updated);
          form.reset(toFormValues(updated));
          toast.success('Workspace updated.');
        }
        ok = true;
      })();
      // The Lifecycle tab's layout draft commits with the same Save (BL-064).
      if (ok) lifecycleLayoutController.current?.save();
      return ok;
    };

    const onCancel = () => {
      if (creating) router.push(workspacesListPath);
      else form.reset(toFormValues(workspace));
      lifecycleLayoutController.current?.discard();
    };

    const tabs = [
      {
        id: 'settings',
        label: 'Settings',
        icon: SettingsIcon,
        render: ({ editing }: { editing: boolean }) => (
          <SettingsTab form={form} editing={editing} creating={creating} workspace={workspace} />
        ),
      },
      {
        id: 'channels',
        label: 'Channels',
        icon: MessageCircle,
        render: () => <ChannelsTab workspaceId={workspace?.id ?? null} creating={creating} />,
      },
      {
        id: 'members',
        label: 'Members',
        icon: UsersIcon,
        render: () => <MembersTab workspaceId={workspace?.id ?? null} creating={creating} />,
      },
      // Plan 25 - hidden while creating (AC-CDM-29): these hang off a real
      // workspace id (scoped lifecycle graph / per-workspace registries).
      ...(!creating
        ? [
            {
              id: 'lifecycle',
              label: 'Lifecycle',
              icon: GitBranch,
              render: ({ editing }: { editing: boolean }) =>
                workspace ? (
                  <WorkspaceLifecycleTab
                    workspaceId={workspace.id}
                    workspaceName={workspace.name}
                    editing={editing}
                    onDirtyChange={setLifecycleDirty}
                    layoutController={lifecycleLayoutController}
                  />
                ) : null,
            },
            {
              id: 'contact-fields',
              label: 'Contact fields',
              icon: FormInput,
              render: () => <WorkspaceContactFieldsTab workspaceId={workspace?.id ?? null} creating={creating} />,
            },
            {
              id: 'tags',
              label: 'Tags',
              icon: Tag,
              render: () => <WorkspaceTagsTab workspaceId={workspace?.id ?? null} creating={creating} />,
            },
          ]
        : []),
      ...(can('api_keys.read')
        ? [
            {
              id: 'api-keys',
              label: 'API Keys',
              icon: KeyRound,
              render: () => <ApiKeysTab workspaceId={workspace?.id ?? null} creating={creating} />,
            },
          ]
        : []),
    ];

    return {
      breadcrumb: [
        { label: 'Home', href: '/' },
        { label: 'Omnichannel', href: workspacesListPath },
        { label: 'Workspaces', href: workspacesListPath },
        { label: creating ? 'New workspace' : (workspace?.name ?? 'Workspace') },
      ],
      backHref: workspacesListPath,
      backLabel: 'Back to workspaces',
      title: creating ? 'New workspace' : (workspace?.name ?? 'Workspace'),
      subtitle: creating ? 'Create a messaging workspace' : undefined,
      tabs,
      initialTabId: 'settings',
      actions,
      actionRows: workspace ? [workspace] : [],
      editable: !creating,
      editPermission: 'workspaces.manage',
      initialEditing: creating ? true : initialEditing,
      isDirty: form.formState.isDirty || lifecycleDirty,
      onSave,
      onCancel,
      recordNav: creating
        ? undefined
        : {
            fetchAt: (query, index) =>
              workspaceService.getAt(query, index).then((r) => ({
                recordId: r.workspace?.id ?? null,
                total: r.total,
              })),
            buildHref: (recordId, ctx, index) => workspaceFormHref(recordId, { ctx, index }),
          },
    };
  }, [
    isLoading,
    notFound,
    creating,
    workspace,
    actions,
    form,
    initialEditing,
    workspaceId,
    router,
    can,
    lifecycleDirty,
  ]);

  return { config, form, isLoading, notFound };
}
