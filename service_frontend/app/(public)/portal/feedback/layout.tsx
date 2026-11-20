'use client';

import type { ReactNode } from 'react';
import { PortalRoot } from '@/components/platform/idea-portal';

/** Idea portal (lane IDEA-PORTAL): sign-in required; owns its chrome. */
export default function IdeaPortalLayout({ children }: { children: ReactNode }) {
  return <PortalRoot>{children}</PortalRoot>;
}
