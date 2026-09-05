'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ChevronDown, ChevronUp, LogOut, UserCog } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useImpersonation } from '@/hooks/use-impersonation';

const COLLAPSE_KEY = 'foundryx.impersonation.collapsed';

/**
 * Top banner shown while impersonating (plan 03 §13). Collapsible (collapses to a
 * small pill so it never blocks controls); offers Exit. Records created while
 * impersonating stay attributed to the real admin (enforced server-side).
 */
export function ImpersonationBanner() {
  const { session, stop, hydrate, pending } = useImpersonation();
  const router = useRouter();
  const bannerRef = useRef<HTMLDivElement>(null);

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

  const expanded = Boolean(session) && !collapsed;

  // Publishes the REAL rendered banner height (never a guessed constant - the copy
  // wraps to two lines under ~640px, and a hardcoded height silently undercounts
  // that) as --shell-top-offset. header.tsx/sidebar.tsx read it for their own `top`;
  // demo1.css's wrapper padding-top and the settings-sidebar sticky nav read
  // `calc(var(--header-height) + var(--shell-top-offset, 0px))` so the banner pushes
  // the WHOLE shell down, not just the header - T1 fix round 1 finding 1 was the
  // wrapper (and everything below the header) staying put while the header alone
  // dropped, hiding the page title under it. The collapsed pill floats and never
  // spans the top, so it publishes 0.
  useEffect(() => {
    if (typeof document === 'undefined') return;
    if (!expanded) {
      document.documentElement.style.setProperty('--shell-top-offset', '0px');
      return;
    }
    const el = bannerRef.current;
    if (!el) return;
    const publish = () => {
      document.documentElement.style.setProperty('--shell-top-offset', `${el.offsetHeight}px`);
    };
    publish();
    const observer = new ResizeObserver(publish);
    observer.observe(el);
    return () => observer.disconnect();
  }, [expanded]);

  // Clears the offset entirely on unmount (session ended, component torn down) so a
  // stale value never survives past the banner that set it.
  useEffect(() => {
    return () => {
      if (typeof document !== 'undefined') {
        document.documentElement.style.removeProperty('--shell-top-offset');
      }
    };
  }, []);

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
        className="fixed end-3 top-2 z-(--z-banner) flex items-center gap-1 rounded-full border border-amber-300 bg-amber-100 px-2.5 py-1 text-xs font-medium text-amber-900 shadow-sm hover:bg-amber-200"
      >
        <UserCog className="size-3.5" />
        Impersonating
        <ChevronDown className="size-3.5" />
      </button>
    );
  }

  return (
    <div
      ref={bannerRef}
      role="status"
      className="fixed inset-x-0 top-0 z-(--z-banner) border-b border-amber-300 bg-amber-100 px-4 py-2 text-amber-900 shadow-sm"
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
            aria-label="Hide banner"
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
