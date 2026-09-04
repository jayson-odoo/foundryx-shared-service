'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { zodResolver } from '@hookform/resolvers/zod';
import { useSession } from 'next-auth/react';
import { useForm, type UseFormReturn } from 'react-hook-form';
import { KeyRound, Shield, User as UserIcon } from 'lucide-react';
import { toast } from 'sonner';
import type { ResourceFormConfig } from '@/components/platform/resource-form';
import type { ListQuery } from '@/types/resource';
import { userService } from '@/services/user-service';
import { rolesService } from '@/services/roles-service';
import type { Role, User } from '@/types/user';
import { AvatarUpload } from '@/components/platform/avatar-upload';
import { UserAvatar } from '@/components/platform/user-avatar';
import { useCan } from '@/hooks/use-can';
import { useUserAvatar } from '@/hooks/use-avatar';
import { ProfileTab, SecurityTab, ActivityTab } from './user-form-fields';
import { useUserActions } from './use-user-actions';
import { userFormHref, userFormPath, usersListPath } from './paths';
import { userFormSchema, type UserFormValues } from './user-schema';

function toFormValues(user: User | null): UserFormValues {
  if (!user) return { name: '', email: '', roleIds: [], status: 'ACTIVE' };
  return {
    name: user.name ?? '',
    email: user.email,
    roleIds: user.roles.map((r) => r.id),
    status: user.status === 'INVITED' ? 'ACTIVE' : user.status,
  };
}

export interface UseUserFormResult {
  config: ResourceFormConfig<User> | null;
  form: UseFormReturn<UserFormValues>;
  isLoading: boolean;
  notFound: boolean;
}

/** Loads the record + roles, wires RHF, and assembles the form config. */
export function useUserForm(userId: string | undefined, initialEditing: boolean): UseUserFormResult {
  const router = useRouter();
  const actions = useUserActions();
  const creating = !userId;
  const { data: session } = useSession();
  // Own record: email locked on this form - the /account ceremony owns it
  // (plan sprint-2/04, no self-bypass; the backend 409s it anyway).
  const isSelf = !creating && session?.user.id === userId;
  const { can } = useCan();
  const userAvatar = useUserAvatar(userId ?? '');

  const [user, setUser] = useState<User | null>(null);
  const [roles, setRoles] = useState<Role[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  const form = useForm<UserFormValues>({
    resolver: zodResolver(userFormSchema),
    defaultValues: toFormValues(null),
  });

  // Load roles once.
  useEffect(() => {
    rolesService.list().then(setRoles);
  }, []);

  // Load the record (or start blank for create).
  useEffect(() => {
    let active = true;
    if (creating) {
      setUser(null);
      form.reset(toFormValues(null));
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    userService
      .get(userId)
      .then((u) => {
        if (!active) return;
        setUser(u);
        form.reset(toFormValues(u));
        setNotFound(false);
      })
      .catch(() => active && setNotFound(true))
      .finally(() => active && setIsLoading(false));
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId, creating]);

  // Stable across renders (fix round 2, AC-DLA-30/31 D7) - use-record-nav.ts's
  // prefetch effect lists these in its deps array; an inline closure here
  // would recreate them every render and re-arm the prefetch/total-resolve
  // fetch on every render instead of only on ctx/index changes.
  const fetchRecordAt = useCallback(
    (query: ListQuery, index: number) =>
      userService.getAt(query, index).then((r) => ({
        recordId: r.user?.id ?? null,
        total: r.total,
      })),
    [],
  );
  const buildRecordHref = useCallback(
    (recordId: string, ctx: string, index: number) => userFormHref(recordId, { ctx, index }),
    [],
  );

  const config = useMemo<ResourceFormConfig<User> | null>(() => {
    if (isLoading || notFound) return null;

    const onSave = async (): Promise<boolean> => {
      let ok = false;
      await form.handleSubmit(async (values) => {
        if (creating) {
          const created = await userService.create({
            name: values.name,
            email: values.email,
            roleIds: values.roleIds,
            status: values.status,
          });
          toast.success('User created - invitation sent.');
          router.push(userFormPath(created.id));
        } else {
          const updated = await userService.update(userId, {
            name: values.name,
            // Admin instant path (plan 04) - own email never rides this PATCH.
            email: isSelf ? undefined : values.email,
            roleIds: values.roleIds,
            // INVITED is system-managed - don't let a save flip it.
            status: user?.status === 'INVITED' ? undefined : values.status,
          });
          setUser(updated);
          form.reset(toFormValues(updated));
          toast.success('User updated.');
        }
        ok = true;
      })();
      return ok;
    };

    const onCancel = () => {
      if (creating) router.push(usersListPath);
      else form.reset(toFormValues(user));
    };

    const tabs = creating
      ? [
          {
            id: 'profile',
            label: 'Profile',
            icon: UserIcon,
            render: ({ editing }: { editing: boolean }) => (
              <ProfileTab form={form} editing={editing} creating user={null} roles={roles} />
            ),
          },
        ]
      : [
          {
            id: 'profile',
            label: 'Profile',
            icon: UserIcon,
            render: ({ editing }: { editing: boolean }) => (
              <ProfileTab
                form={form}
                editing={editing}
                creating={false}
                isSelf={isSelf}
                user={user}
                roles={roles}
              />
            ),
          },
          {
            id: 'security',
            label: 'Security',
            icon: Shield,
            render: () => (user ? <SecurityTab user={user} /> : null),
          },
          {
            id: 'activity',
            label: 'Activity',
            icon: KeyRound,
            render: () => <ActivityTab />,
          },
        ];

    return {
      breadcrumb: [
        { label: 'Home', href: '/' },
        { label: 'User Management', href: usersListPath },
        { label: 'Users', href: usersListPath },
        { label: creating ? 'New user' : (user?.name ?? 'User') },
      ],
      backHref: usersListPath,
      backLabel: 'Back to users',
      title: creating ? 'New user' : (user?.name ?? 'User'),
      subtitle: creating ? 'Invite a new user' : (user?.email ?? undefined),
      // Others' avatars: interactive upload (admin path, applies immediately -
      // branding-asset convention). Own row stays read-only here; /account is
      // the self-service surface (plan 06 D5).
      avatar: creating
        ? undefined
        : user
          ? !isSelf && can('users.update')
            ? (
                <AvatarUpload
                  name={user.name}
                  email={user.email}
                  avatar={user.avatar}
                  onUpload={async (blob) => {
                    const url = await userAvatar.upload(blob);
                    setUser((prev) => (prev ? { ...prev, avatar: url } : prev));
                  }}
                  onRemove={async () => {
                    await userAvatar.remove();
                    setUser((prev) => (prev ? { ...prev, avatar: null } : prev));
                  }}
                />
              )
            : <UserAvatar user={user} size="lg" />
          : undefined,
      tabs,
      actions,
      actionRows: user ? [user] : [],
      editable: !creating,
      editPermission: 'users.update',
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
    isSelf,
    user,
    roles,
    actions,
    form,
    initialEditing,
    userId,
    router,
    can,
    userAvatar,
    fetchRecordAt,
    buildRecordHref,
  ]);

  return { config, form, isLoading, notFound };
}
