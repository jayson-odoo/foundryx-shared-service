'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm, type UseFormReturn } from 'react-hook-form';
import { KeyRound, Settings as SettingsIcon, Users as UsersIcon } from 'lucide-react';
import { toast } from 'sonner';
import type { ResourceFormConfig } from '@/components/platform/resource-form';
import { roleService } from '@/services/role-service';
import { permissionService } from '@/services/permission-service';
import type { PermissionCatalog } from '@/types/permission';
import type { RoleDetail, RoleListItem } from '@/types/role';
import { PermissionsTab, AssignedUsersTab, SettingsTab } from './role-form-fields';
import { useRoleActions } from './use-role-actions';
import { roleFormHref, roleFormPath, rolesListPath } from './paths';
import { roleFormSchema, type RoleFormValues } from './role-schema';

function toFormValues(role: RoleDetail | null): RoleFormValues {
  if (!role) return { name: '', description: '', permissionKeys: [], isSystem: false };
  return {
    name: role.name,
    description: role.description ?? '',
    permissionKeys: [...role.permissionKeys],
    isSystem: role.isSystem,
  };
}

export interface UseRoleFormResult {
  config: ResourceFormConfig<RoleListItem> | null;
  form: UseFormReturn<RoleFormValues>;
  isLoading: boolean;
  notFound: boolean;
}

/** Loads the record + permission catalog, wires RHF, and assembles the form config. */
export function useRoleForm(roleId: string | undefined, initialEditing: boolean): UseRoleFormResult {
  const router = useRouter();
  const actions = useRoleActions();
  const creating = !roleId;

  const [role, setRole] = useState<RoleDetail | null>(null);
  const [catalog, setCatalog] = useState<PermissionCatalog>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  const form = useForm<RoleFormValues>({
    resolver: zodResolver(roleFormSchema),
    defaultValues: toFormValues(null),
  });

  // Load the permission catalog once.
  useEffect(() => {
    permissionService.catalog().then(setCatalog).catch(() => setCatalog([]));
  }, []);

  // Load the record (or start blank for create).
  useEffect(() => {
    let active = true;
    if (creating) {
      setRole(null);
      form.reset(toFormValues(null));
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    roleService
      .get(roleId)
      .then((r) => {
        if (!active) return;
        setRole(r);
        form.reset(toFormValues(r));
        setNotFound(false);
      })
      .catch(() => active && setNotFound(true))
      .finally(() => active && setIsLoading(false));
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roleId, creating]);

  const config = useMemo<ResourceFormConfig<RoleListItem> | null>(() => {
    if (isLoading || notFound) return null;

    const onSave = async (): Promise<boolean> => {
      let ok = false;
      await form.handleSubmit(async (values) => {
        const payload = {
          name: values.name,
          description: values.description.trim() ? values.description.trim() : null,
          permissionKeys: values.permissionKeys,
          isSystem: values.isSystem,
        };
        if (creating) {
          const created = await roleService.create(payload);
          toast.success('Role created.');
          router.push(roleFormPath(created.id));
        } else {
          const updated = await roleService.update(roleId, payload);
          setRole(updated);
          form.reset(toFormValues(updated));
          toast.success('Role updated.');
        }
        ok = true;
      })();
      return ok;
    };

    const onCancel = () => {
      if (creating) router.push(rolesListPath);
      else form.reset(toFormValues(role));
    };

    const tabs = [
      {
        id: 'permissions',
        label: 'Permissions',
        icon: KeyRound,
        render: ({ editing }: { editing: boolean }) => (
          <PermissionsTab form={form} editing={editing} catalog={catalog} />
        ),
      },
      {
        id: 'assigned',
        label: 'Assigned Users',
        icon: UsersIcon,
        render: () => <AssignedUsersTab roleId={role?.id ?? null} creating={creating} />,
      },
      {
        id: 'settings',
        label: 'Settings',
        icon: SettingsIcon,
        render: ({ editing }: { editing: boolean }) => (
          <SettingsTab form={form} editing={editing} role={role} creating={creating} />
        ),
      },
    ];

    return {
      breadcrumb: [
        { label: 'Home', href: '/' },
        { label: 'User Management', href: rolesListPath },
        { label: 'Roles', href: rolesListPath },
        { label: creating ? 'New role' : (role?.name ?? 'Role') },
      ],
      backHref: rolesListPath,
      backLabel: 'Back to roles',
      title: creating ? 'New role' : (role?.name ?? 'Role'),
      subtitle: creating ? 'Define a new role and its permissions' : (role?.description ?? undefined),
      tabs,
      // Create opens on Settings (name first); view/edit lead with Permissions.
      initialTabId: creating ? 'settings' : 'permissions',
      actions,
      actionRows: role ? [role] : [],
      editable: !creating,
      editPermission: 'roles.update',
      initialEditing: creating ? true : initialEditing,
      isDirty: form.formState.isDirty,
      onSave,
      onCancel,
      recordNav: creating
        ? undefined
        : {
            fetchAt: (query, index) =>
              roleService.getAt(query, index).then((r) => ({
                recordId: r.role?.id ?? null,
                total: r.total,
              })),
            buildHref: (recordId, ctx, index) => roleFormHref(recordId, { ctx, index }),
          },
    };
  }, [isLoading, notFound, creating, role, catalog, actions, form, initialEditing, roleId, router]);

  return { config, form, isLoading, notFound };
}
