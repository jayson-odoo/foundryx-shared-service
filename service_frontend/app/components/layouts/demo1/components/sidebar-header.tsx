'use client';

import Link from 'next/link';
import { ChevronFirst } from 'lucide-react';
import { toAbsoluteUrl } from '@/lib/helpers';
import { cn } from '@/lib/utils';
import { useTenantBranding } from '@/hooks/use-branding';
import { useSettings } from '@/providers/settings-provider';
import { Button } from '@/components/ui/button';

export function SidebarHeader() {
  const { settings, storeOption } = useSettings();
  const { branding } = useTenantBranding();

  const handleToggleClick = () => {
    storeOption(
      'layouts.demo1.sidebarCollapse',
      !settings.layouts.demo1.sidebarCollapse,
    );
  };

  return (
    <div className="sidebar-header hidden lg:flex items-center relative justify-between px-3 lg:px-6 shrink-0">
      <Link href="/">
        {branding.logoUrl ? (
          // Tenant logo (sprint-2/03) on a primary chip - the same surface the
          // sign-in panel gives it, so white/transparent logos stay visible.
          // Toggle classes live on a bare wrapper with NO display utilities,
          // so the demo1 collapse CSS (`.small-logo { display:none }`) wins;
          // the chip styling sits on the inner element.
          <>
            <span className="default-logo">
              <span className="inline-flex h-[32px] items-center rounded-lg bg-primary px-2.5">
                <img
                  src={branding.logoUrl}
                  className="h-[20px] w-auto max-w-[150px] object-contain"
                  alt="Logo"
                />
              </span>
            </span>
            {/* Collapsed slot - the square favicon fits best; wordmark logo
                only as a fallback. */}
            <span className="small-logo">
              <span className="inline-flex size-[32px] items-center justify-center overflow-hidden rounded-lg bg-primary">
                <img
                  src={branding.faviconUrl ?? branding.logoUrl}
                  className="h-[18px] w-auto max-w-[24px] object-contain"
                  alt="Logo"
                />
              </span>
            </span>
          </>
        ) : (
          <>
            <div className="dark:hidden">
              <img
                src={toAbsoluteUrl('/media/app/default-logo.svg')}
                className="default-logo h-[22px] max-w-none"
                alt="Default Logo"
              />
              <img
                src={toAbsoluteUrl('/media/app/mini-logo.svg')}
                className="small-logo h-[22px] max-w-none"
                alt="Mini Logo"
              />
            </div>
            <div className="hidden dark:block">
              <img
                src={toAbsoluteUrl('/media/app/default-logo-dark.svg')}
                className="default-logo h-[22px] max-w-none"
                alt="Default Dark Logo"
              />
              <img
                src={toAbsoluteUrl('/media/app/mini-logo.svg')}
                className="small-logo h-[22px] max-w-none"
                alt="Mini Logo"
              />
            </div>
          </>
        )}
      </Link>
      <Button
        onClick={handleToggleClick}
        size="sm"
        mode="icon"
        variant="outline"
        className={cn(
          'size-7 absolute start-full top-2/4 rtl:translate-x-2/4 -translate-x-2/4 -translate-y-2/4',
          settings.layouts.demo1.sidebarCollapse
            ? 'ltr:rotate-180'
            : 'rtl:rotate-180',
        )}
      >
        <ChevronFirst className="size-4!" />
      </Button>
    </div>
  );
}
