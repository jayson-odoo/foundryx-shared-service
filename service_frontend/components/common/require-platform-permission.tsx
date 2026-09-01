'use client';

import type { ReactNode } from 'react';
import { useSession } from 'next-auth/react';
import { useCan } from '@/hooks/use-can';
import { NoPermission } from './no-permission';

export interface RequirePlatformPermissionProps {
  permission: string;
  children: ReactNode;
}

/**
 * Route-level gate for platform-admin-only surfaces (Meetings S4 R5): the
 * session must belong to the platform tenant AND hold `permission` - the
 * same conjunction the sidebar uses to decide `showPlatform`
 * (`sidebar-menu.tsx`). A non-platform user sees the friendly NoPermission
 * page rather than content whose API calls would just 403.
 */
export function RequirePlatformPermission({ permission, children }: RequirePlatformPermissionProps) {
  const { data: session, status } = useSession();
  const { can, ready } = useCan();
  // Wait for the session before deciding, to avoid flashing the gate on load.
  if (!ready || status === 'loading') return null;
  const isPlatformAdmin = session?.user?.isPlatformTenant === true && can(permission);
  if (!isPlatformAdmin) return <NoPermission />;
  return <>{children}</>;
}
