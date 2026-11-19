'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { zodResolver } from '@hookform/resolvers/zod';
import { useSession } from 'next-auth/react';
import { useForm, type UseFormReturn } from 'react-hook-form';
import { KeyRound, Mail, User as UserIcon } from 'lucide-react';
import { toast } from '@/lib/toast';
import { z } from 'zod';
import type { ResourceFormConfig } from '@/components/platform/resource-form';
import { AvatarUpload } from '@/components/platform/avatar-upload';
import { accountService } from '@/services/account-service';
import { useEmailChange, type UseEmailChangeResult } from '@/hooks/use-email-change';
import { useOwnAvatar } from '@/hooks/use-avatar';
import { useFx } from '@/hooks/use-fx';
import { AccountProfileTab } from './account-form-fields';

export const accountFormSchema = z.object({
  name: z.string().min(1, 'Name is required.'),
});

export type AccountFormValues = z.infer<typeof accountFormSchema>;

// Survives the post-update() remount (same reason as the avatar override -
// update() flips useSession to 'loading' and the page remounts, plan 04
// lesson). Bridges Phase A, where the mock isn't behind /auth/me.
let nameOverride: string | undefined;

/** Test helper - module state would leak across specs otherwise. */
export function __resetAccountNameOverride(): void {
  nameOverride = undefined;
}

export interface UseAccountFormResult {
  config: ResourceFormConfig<never>;
  form: UseFormReturn<AccountFormValues>;
  emailChange: UseEmailChangeResult;
  dialogOpen: boolean;
  setDialogOpen: (open: boolean) => void;
  email: string;
}

/**
 * My Account on the Resource form shell (plan 06 - system principle: every
 * form surface = ResourceForm with the global Edit toggle). Self-scope:
 * name is editable (PATCH /me/profile); email rides the plan-04 ceremony;
 * roles read-only.
 */
export function useAccountForm(): UseAccountFormResult {
  const router = useRouter();
  const { data: session, update } = useSession();
  const emailChange = useEmailChange();
  const ownAvatar = useOwnAvatar();
  const [dialogOpen, setDialogOpen] = useState(false);
  const fx = useFx();

  const user = session?.user;
  const displayName = nameOverride ?? user?.name ?? null;
  const email = user?.email ?? '';
  const roles = useMemo(() => user?.roles ?? [], [user?.roles]);

  const form = useForm<AccountFormValues>({
    mode: 'onTouched',
    resolver: zodResolver(accountFormSchema),
    defaultValues: { name: displayName ?? '' },
  });

  // Session arrives async on hard loads - seed the form once it lands.
  useEffect(() => {
    if (!form.formState.isDirty) form.reset({ name: nameOverride ?? user?.name ?? '' });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.name]);

  const onSave = async (): Promise<boolean> => {
    const valid = await form.trigger();
    if (!valid) return false;
    const values = form.getValues();
    const before = displayName;
    try {
      const result = await accountService.updateProfile({ name: values.name.trim() });
      nameOverride = result.name;
      form.reset({ name: result.name });
      if (fx) {
        toast.fxDone({
          what: `Name changed to ${result.name}`,
          // The same request with the earlier name puts it back.
          undo:
            before && before !== result.name
              ? () => void undoName(before)
              : undefined,
        });
      } else {
        toast.success('Profile saved.');
      }
      // Session catches up (name rides the jwt update branch).
      await update();
      return true;
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Save failed.');
      return false;
    }
  };

  const undoName = async (name: string): Promise<void> => {
    try {
      const result = await accountService.updateProfile({ name });
      nameOverride = result.name;
      form.reset({ name: result.name });
      await update();
    } catch {
      toast.error("Couldn't undo. Your new name stays.");
    }
  };

  const config = useMemo<ResourceFormConfig<never>>(
    () => ({
      breadcrumb: [{ label: 'Home', href: '/' }, { label: 'My Account' }],
      backHref: '/',
      backLabel: 'Back to dashboard',
      title: displayName ?? 'My Account',
      subtitle: email || undefined,
      avatar: (
        <AvatarUpload
          name={displayName}
          email={email}
          avatar={ownAvatar.avatar}
          onUpload={ownAvatar.upload}
          onRemove={ownAvatar.remove}
        />
      ),
      tabs: [
        {
          id: 'profile',
          label: 'Profile',
          icon: UserIcon,
          render: ({ editing }) => (
            <AccountProfileTab
              form={form}
              editing={editing}
              name={displayName}
              email={email}
              roles={roles}
              emailChange={emailChange}
            />
          ),
        },
      ],
      // Sign-in concerns live in the "…" menu (user feedback - the dedicated
      // Security tab read as clutter for two buttons).
      actions: [
        {
          id: 'change-email',
          label: 'Change email',
          icon: Mail,
          surfaces: { form: true },
          run: () => setDialogOpen(true),
        },
        {
          id: 'reset-password',
          label: 'Reset password',
          icon: KeyRound,
          surfaces: { form: true },
          run: () => router.push('/reset-password'),
        },
      ],
      actionRows: [{} as never],
      editable: true,
      // Self-scope - perm-free like /auth/me; no editPermission gate.
      initialEditing: false,
      isDirty: form.formState.isDirty,
      onSave,
      onCancel: () => form.reset({ name: displayName ?? '' }),
      // Foundryx UIUX switch only: Edit / "Save profile" is the page's red
      // action; Change email and Reset password are icon actions beside it.
      ...(fx
        ? {
            entityNoun: 'profile',
            fx: {
              mainActionId: 'save',
              iconFor: {
                'change-email': 'email',
                'reset-password': <KeyRound aria-hidden="true" className="size-[18px]" />,
              },
              discardName: 'your profile',
            },
          }
        : {}),
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [displayName, email, roles, ownAvatar, emailChange, form, form.formState.isDirty, router, fx],
  );

  return { config, form, emailChange, dialogOpen, setDialogOpen, email };
}
