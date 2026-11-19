'use client';

/**
 * The impersonation banner while the Foundryx UIUX switch is on: a system
 * banner in the `warn` set ("signed in as someone else"), shown by the banner
 * bar above the top bar, with "Stop viewing as <name>" as its one text button.
 *
 * SS keeps its "Hide banner" control (an agreed difference, playbook-uiux.md):
 * hidden, it folds to the same small pill as today, remembered under the same
 * key, and while folded it pushes nothing down. The session handling (hydrate
 * on mount, exit, reload) is the legacy banner's, unchanged.
 */
import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ChevronDown, UserCog } from 'lucide-react';
import { useImpersonation } from '@/hooks/use-impersonation';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { cn } from '@/lib/utils';
import { useSystemBanner, type FxBanner } from './banner-store';

const COLLAPSE_KEY = 'foundryx.impersonation.collapsed';

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSE_KEY) === '1';
  } catch {
    return false;
  }
}

export function FxImpersonationBanner() {
  const { session, stop, hydrate, pending } = useImpersonation();
  const router = useRouter();
  const [collapsed, setCollapsed] = useState<boolean>(() =>
    typeof window === 'undefined' ? false : readCollapsed(),
  );

  useEffect(() => {
    void hydrate();
  }, [hydrate]);

  useEffect(() => {
    try {
      window.localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0');
    } catch {
      // Storage blocked: the choice lasts for this page only.
    }
  }, [collapsed]);

  const targetName = session
    ? session.targetUser.name || session.targetUser.email
    : '';
  const targetId = session?.targetUser.id;

  const banner = useMemo<FxBanner | null>(() => {
    if (!session || collapsed) return null;
    const onExit = async () => {
      await stop();
      router.refresh();
      if (typeof window !== 'undefined') window.location.reload();
    };
    return {
      id: 'impersonation',
      tone: 'warn',
      text: (
        <>
          Viewing as{' '}
          <Link
            href={`/user-management/users/${targetId}`}
            className="font-semibold underline underline-offset-2"
          >
            {targetName}
          </Link>
          . Anything you create or change is still recorded under your own
          account.
        </>
      ),
      action: {
        label: `Stop viewing as ${targetName}`,
        onClick: () => void onExit(),
        disabled: pending,
      },
      hide: { label: 'Hide banner', onHide: () => setCollapsed(true) },
    };
  }, [session, collapsed, stop, router, pending, targetId, targetName]);

  useSystemBanner(banner);

  if (!session || !collapsed) return null;

  return (
    <button
      type="button"
      onClick={() => setCollapsed(false)}
      title="Show impersonation banner"
      className={cn(
        PRESSED_CLASS,
        'fixed end-3 top-2 z-(--z-banner) flex items-center gap-1 rounded-(--fx-r-pill) bg-(--fx-warn-bg) px-2.5 py-1 text-xs font-semibold text-(--fx-warn-ink) shadow-[0_4px_12px_var(--fx-shade)]',
      )}
    >
      <UserCog className="size-3.5" aria-hidden="true" />
      Viewing as {targetName}
      <ChevronDown className="size-3.5" aria-hidden="true" />
    </button>
  );
}
