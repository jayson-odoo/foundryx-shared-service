'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useSession } from 'next-auth/react';
import { LoaderCircleIcon } from 'lucide-react';
import { PortalDashboard } from './portal-dashboard';

/**
 * Portal landing (Cluster E, slice 0b — AC-06-24/25). ONE unified dashboard
 * aggregating every surface the Profile can access across all events. Reads the
 * PORTAL session; redirects to /portal/login when unauthenticated. No
 * persona/context picker on entry — the dashboard composes from the surfaces
 * the backend gates the Profile into.
 */
export default function Page() {
  const router = useRouter();
  const { status } = useSession();

  useEffect(() => {
    if (status === 'unauthenticated') router.push('/portal/login');
  }, [status, router]);

  if (status === 'loading' || status === 'unauthenticated') {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <LoaderCircleIcon className="size-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return <PortalDashboard />;
}
