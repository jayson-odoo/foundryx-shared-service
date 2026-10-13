'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import type { ReactNode } from 'react';
import { LogOut } from 'lucide-react';
import { BrandMark } from '@/components/platform/branding';
import { useTenantBranding } from '@/hooks/use-branding';
import { usePublicPageBranding } from '@/app/(public)/public-branded-shell';
import { useIdeaPortal } from '@/hooks/use-idea-portal';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export interface PortalShellProps {
  children: ReactNode;
}

function initials(name: string | null): string {
  const parts = (name ?? '').trim().split(/\s+/).filter(Boolean);
  return (parts[0]?.[0] ?? '?').toUpperCase() + (parts[1]?.[0] ?? '').toUpperCase();
}

/**
 * Portal chrome: tenant brand + Submit + the signed-in person, then the
 * Roadmap / Feedback / Changelog tabs (each its own route). Inside the Sorento
 * iframe (`mode: 'embed'`) only the tabs render - Sorento owns the header.
 */
export function PortalShell({ children }: PortalShellProps) {
  const { mode, paths, principal, signOut } = useIdeaPortal();
  const pathname = usePathname() ?? '';
  const shellBranding = usePublicPageBranding();
  const { branding: live, isResolved } = useTenantBranding();
  const branding = shellBranding ?? live;

  const tabs = [
    { href: paths.roadmap, label: 'Roadmap', active: pathname === paths.roadmap },
    { href: paths.feedback, label: 'Feedback', active: pathname.startsWith(paths.feedback) },
    { href: paths.changelog, label: 'Changelog', active: pathname.startsWith(paths.changelog) },
  ];

  return (
    <div className="flex min-h-full w-full grow flex-col bg-muted/20">
      <header className="border-b border-border bg-background">
        {mode === 'portal' && (
          <div className="mx-auto flex w-full max-w-6xl items-center gap-3 px-4 py-3">
            {(shellBranding || isResolved) && <BrandMark branding={branding} />}
            <div className="ml-auto flex items-center gap-2">
              <Button asChild size="sm" className="hidden sm:inline-flex">
                <Link href={`${paths.feedback}#submit`}>Submit an idea</Link>
              </Button>
              <span
                className="flex size-8 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary"
                title={`${principal.name ?? ''} (${principal.role})`}
                data-testid="portal-avatar"
              >
                {initials(principal.name)}
              </span>
              <Button variant="ghost" size="sm" mode="icon" aria-label="Sign out" onClick={signOut}>
                <LogOut className="size-4" />
              </Button>
            </div>
          </div>
        )}
        <nav className="mx-auto flex w-full max-w-6xl gap-1 overflow-x-auto px-4 text-sm" aria-label="Portal">
          {tabs.map((t) => (
            <Link
              key={t.href}
              href={t.href}
              aria-current={t.active ? 'page' : undefined}
              className={cn(
                'border-b-2 px-3 py-2 whitespace-nowrap transition-colors',
                t.active
                  ? 'border-primary text-primary'
                  : 'border-transparent text-muted-foreground hover:text-foreground',
              )}
            >
              {t.label}
            </Link>
          ))}
        </nav>
      </header>
      <main className="mx-auto flex w-full min-w-0 max-w-6xl flex-col gap-4 px-4 py-6">{children}</main>
    </div>
  );
}
