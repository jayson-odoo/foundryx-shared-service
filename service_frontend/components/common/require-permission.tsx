'use client';

import type { ReactNode } from 'react';
import { useCan } from '@/hooks/use-can';
import { NoPermission } from './no-permission';

export interface RequirePermissionProps {
  permission: string;
  children: ReactNode;
}

/**
 * Route-level gate: renders the friendly NoPermission page when the user lacks
 * `permission`, otherwise the children. Backend still enforces — this just keeps
 * the user out of a page that would 403 (plan 03 §3.4).
 */
export function RequirePermission({ permission, children }: RequirePermissionProps) {
  const { can, ready } = useCan();
  // Wait for the session before deciding, to avoid flashing the gate on load.
  if (!ready) return null;
  if (!can(permission)) return <NoPermission />;
  return <>{children}</>;
}
