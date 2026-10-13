'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { BrandMark } from '@/components/platform/branding';
import { useTenantBranding } from '@/hooks/use-branding';
import { usePublicPageBranding } from '@/app/(public)/public-branded-shell';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';

/** Portal sign-in: staff only - salespeople and office staff sign in with
 * their staff login (owner Q1, 13 Oct). */
export function PortalSignIn() {
  const pathname = usePathname() ?? '/portal/ideas';
  const shellBranding = usePublicPageBranding();
  const { branding: live } = useTenantBranding();
  const branding = shellBranding ?? live;
  return (
    <div className="mx-auto mt-16 w-full max-w-sm px-4" data-testid="portal-signin">
      <Card>
        <CardContent className="flex flex-col gap-4 py-6">
          <BrandMark branding={branding} />
          <h1 className="font-heading text-lg font-semibold">Sign in to see the roadmap</h1>
          <Button asChild>
            <Link href={`/signin?callbackUrl=${encodeURIComponent(pathname)}`}>Staff sign in</Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
