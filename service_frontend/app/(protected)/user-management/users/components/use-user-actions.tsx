'use client';

import { useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { useSession } from 'next-auth/react';
import { KeyRound, MailCheck, Pencil, RotateCcw, Send, Trash2, UserCog } from 'lucide-react';
import { toast } from '@/lib/toast';
import type { ResourceAction } from '@/components/platform/resource-list';
import { userService } from '@/services/user-service';
import { useImpersonation } from '@/hooks/use-impersonation';
import { useFx } from '@/hooks/use-fx';
import type { User } from '@/types/user';
import { userFormHref } from './paths';

/**
 * The User action registry - one set surfaced in the row "…" menu, the bulk
 * toolbar, and the form "…" menu (plan 02 §3c). Closes over router + service so
 * each action is self-contained.
 */
export function useUserActions(): ResourceAction<User>[] {
  const router = useRouter();
  const { data: session } = useSession();
  const { start } = useImpersonation();
  const selfId = session?.user?.id;
  // Foundryx UIUX switch only: the confirm names who (FX-04) and the done
  // toasts say what, for whom and by whom. Off keeps today's words exactly.
  const fx = useFx();

  return useMemo<ResourceAction<User>[]>(() => {
    const ids = (rows: User[]) => rows.map((r) => r.id);
    const who = (u: User) => u.name?.trim() || u.email;

    return [
      {
        id: 'edit',
        label: 'Edit',
        icon: Pencil,
        permission: 'users.update',
        surfaces: { row: true },
        run: ([user], rt) => {
          if (!user) return;
          router.push(userFormHref(user.id, { ctx: rt.ctx, index: rt.index, edit: true }));
        },
      },
      {
        id: 'send-invitation',
        label: 'Send invitation',
        icon: Send,
        permission: 'users.create',
        surfaces: { row: true, bulk: true, form: true },
        isDisabled: (rows) => !rows.some((r) => r.status === 'INVITED'),
        run: async (rows, rt) => {
          const eligible = rows.filter((r) => r.status === 'INVITED');
          await userService.invite(eligible.map((r) => r.id));
          if (fx) {
            toast.fxDone({
              what:
                eligible.length === 1
                  ? `Invitation sent to ${who(eligible[0])}`
                  : `Invitations sent to ${eligible.length} users`,
              byWhom: 'you',
            });
          } else {
            toast.success(`Invitation sent to ${eligible.length} user(s).`);
          }
          rt.reload();
        },
      },
      {
        id: 'impersonate',
        label: 'Impersonate',
        icon: UserCog,
        permission: 'users.impersonate',
        surfaces: { row: true, form: true },
        // Can't impersonate yourself or a non-active user (backend also guards).
        isVisible: (rows) => rows.length === 1 && rows[0].id !== selfId,
        isDisabled: (rows) => rows.some((r) => r.status !== 'ACTIVE'),
        // DISCLOSED THIRD confirm carve-out (sprint-4/23, T5 report): D2's grace
        // window is a delete/archive-style model - "start impersonating in 10s,
        // Cancel to stop" has no sensible commit semantics (impersonation isn't
        // a record mutation the server can undo/redo the way trash/archive can).
        // Kept as a plain (non-typed) confirm rather than forced into `deferred`.
        confirm: {
          title: fx
            ? (rows) => {
                const who = rows[0]?.name?.trim();
                return who ? `Impersonate ${who}?` : 'Impersonate this user?';
              }
            : 'Impersonate this user?',
          description:
            'You’ll browse the system with this user’s permissions to test their access. Anything you create or change stays recorded under your own account. Exit anytime from the top banner.',
          confirmLabel: 'Impersonate',
        },
        run: async ([user]) => {
          if (!user) return;
          await start(user.id);
          toast.success(`Now impersonating ${user.name ?? user.email}.`);
          if (typeof window !== 'undefined') window.location.reload();
        },
      },
      {
        id: 'reset-password',
        label: 'Reset password',
        icon: KeyRound,
        permission: 'users.update',
        surfaces: { row: true, form: true },
        run: async ([user]) => {
          if (!user) return;
          await userService.resetPassword(user.id);
          if (fx) {
            toast.fxDone({
              what: `Password reset link sent to ${who(user)}`,
              forWhom: user.name ? user.email : undefined,
              byWhom: 'you',
            });
          } else {
            toast.success('Password reset link sent.');
          }
        },
      },
      {
        id: 'resend-verification',
        label: 'Resend verification',
        icon: MailCheck,
        permission: 'users.update',
        surfaces: { row: true, form: true },
        isDisabled: (rows) => rows.every((r) => Boolean(r.emailVerifiedAt)),
        run: async ([user]) => {
          if (!user) return;
          await userService.resendVerification(user.id);
          if (fx) {
            toast.fxDone({
              what: `Verification email sent again to ${who(user)}`,
              forWhom: user.name ? user.email : undefined,
              byWhom: 'you',
            });
          } else {
            toast.success('Verification email resent.');
          }
        },
      },
      {
        id: 'trash',
        label: 'Trash',
        icon: Trash2,
        tone: 'destructive',
        permission: 'users.delete',
        surfaces: { row: true, bulk: true, form: true },
        isVisible: (rows) => rows.length > 0 && rows.every((r) => !r.isTrashed),
        // Grace-window deferred action (sprint-4/23, T5, D2) - no confirm
        // dialog, no `run` (the registered `users.trash` handler commits it
        // server-side); a bulk trash parks ONE row per user behind one
        // countdown.
        // Switch on only: the one-user countdown names them (FX-03).
        deferred: {
          actionKey: 'users.trash',
          entityType: 'user',
          fxName: (rows) => rows[0]?.name || undefined,
        },
      },
      {
        id: 'restore',
        label: 'Restore',
        icon: RotateCcw,
        permission: 'users.delete',
        surfaces: { row: true, bulk: true, form: true },
        isVisible: (rows) => rows.length > 0 && rows.every((r) => r.isTrashed),
        run: async (rows, rt) => {
          await userService.restore(ids(rows));
          if (fx) {
            toast.fxDone({
              what: rows.length === 1 ? `${who(rows[0])} restored` : `${rows.length} users restored`,
              byWhom: 'you',
            });
          } else {
            toast.success(`Restored ${rows.length} user(s).`);
          }
          rt.reload();
        },
      },
    ];
  }, [router, start, selfId, fx]);
}
