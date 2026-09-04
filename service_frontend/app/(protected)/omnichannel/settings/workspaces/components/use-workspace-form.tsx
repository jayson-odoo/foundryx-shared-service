'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm, type UseFormReturn } from 'react-hook-form';
import { KeyRound, MessageCircle, Settings as SettingsIcon, Users as UsersIcon } from 'lucide-react';
import { toast } from 'sonner';
import type { ResourceFormConfig } from '@/components/platform/resource-form';
import type { ListQuery } from '@/types/resource';
import { workspaceService } from '@/services/workspace-service';
import type { Workspace } from '@/types/omnichannel';
import { SettingsTab, ChannelsTab, MembersTab } from './workspace-form-fields';
import { ApiKeysTab } from './workspace-api-keys-tab';
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

  // Stable across renders (fix round 2, AC-DLA-30/31 D7) - see use-user-form.tsx.
  const fetchRecordAt = useCallback(
    (query: ListQuery, index: number) =>
      workspaceService.getAt(query, index).then((r) => ({
        recordId: r.workspace?.id ?? null,
        total: r.total,
      })),
    [],
  );
  const buildRecordHref = useCallback(
    (recordId: string, ctx: string, index: number) => workspaceFormHref(recordId, { ctx, index }),
    [],
  );

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
      return ok;
    };

    const onCancel = () => {
      if (creating) router.push(workspacesListPath);
      else form.reset(toFormValues(workspace));
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
      isDirty: form.formState.isDirty,
      onSave,
      onCancel,
      recordNav: creating
        ? undefined
        : { fetchAt: fetchRecordAt, buildHref: buildRecordHref },
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
    fetchRecordAt,
    buildRecordHref,
  ]);

  return { config, form, isLoading, notFound };
}
