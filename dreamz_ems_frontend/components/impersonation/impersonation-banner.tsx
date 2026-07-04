'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ChevronDown, ChevronUp, LogOut, UserCog } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useImpersonation } from '@/hooks/use-impersonation';

const BANNER_HEIGHT = 40;
const COLLAPSE_KEY = 'dreamz.impersonation.collapsed';

/**
 * Top banner shown while impersonating (plan 03 §13). Collapsible (collapses to a
 * small pill so it never blocks controls); offers Exit. Records created while
 * impersonating stay attributed to the real admin (enforced server-side).
 */
export function ImpersonationBanner() {
  const { session, stop, hydrate, pending } = useImpersonation();
  const router = useRouter();

  // Reconcile the persisted store with the backend on mount (clears a stale
  // session after a logout-without-exit; adopts one started elsewhere).
  useEffect(() => {
    void hydrate();
  }, [hydrate]);
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false;
    return window.localStorage.getItem(COLLAPSE_KEY) === '1';
  });

  useEffect(() => {
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0');
    }
  }, [collapsed]);

  // Push page content down so the fixed bar never covers the top toolbar.
  useEffect(() => {
    if (typeof document === 'undefined') return;
    const apply = Boolean(session) && !collapsed;
    document.body.style.paddingTop = apply ? `${BANNER_HEIGHT}px` : '';
    return () => {
      document.body.style.paddingTop = '';
    };
  }, [session, collapsed]);

  if (!session) return null;

  const targetName = session.targetUser.name || session.targetUser.email;

  const onExit = async () => {
    await stop();
    router.refresh();
    if (typeof window !== 'undefined') window.location.reload();
  };

  if (collapsed) {
    return (
      <button
        type="button"
        onClick={() => setCollapsed(false)}
        title="Show impersonation banner"
        className="fixed end-3 top-2 z-60 flex items-center gap-1 rounded-full border border-amber-300 bg-amber-100 px-2.5 py-1 text-xs font-medium text-amber-900 shadow-sm hover:bg-amber-200"
      >
        <UserCog className="size-3.5" />
        Impersonating
        <ChevronDown className="size-3.5" />
      </button>
    );
  }

  return (
    <div
      role="status"
      className="fixed inset-x-0 top-0 z-60 border-b border-amber-300 bg-amber-100 px-4 py-2 text-amber-900 shadow-sm"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2 text-sm">
          <UserCog className="size-4 shrink-0" />
          <span className="truncate">
            You are impersonating{' '}
            <Link
              href={`/user-management/users/${session.targetUser.id}`}
              className="font-semibold underline underline-offset-2 hover:text-amber-950"
            >
              {targetName}
            </Link>
            . Anything you create or change is still recorded under your own account.
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={onExit}
            disabled={pending}
            className="border-amber-400 bg-white text-amber-900 hover:bg-amber-50"
          >
            <LogOut className="size-3.5" />
            Exit impersonation
          </Button>
          <Button
            variant="ghost"
            size="sm"
            mode="icon"
            onClick={() => setCollapsed(true)}
            title="Hide banner"
            className="text-amber-900 hover:bg-amber-200"
          >
            <ChevronUp className="size-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}
