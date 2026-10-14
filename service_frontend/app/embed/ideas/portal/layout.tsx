'use client';

import type { ReactNode } from 'react';
import { EmbedPortalRoot } from '@/components/platform/idea-portal';
import { embedAuthStore } from '@/lib/embed-auth-store';
import { EmbedExpired, EmbedLoading, useEmbedSession } from '../embed-session';

/** The idea portal inside Sorento CRM (owner note on mock v1): the SAME
 * portal tabs + idea page, behind the existing ideation embed SSO. */
export default function EmbedIdeaPortalLayout({ children }: { children: ReactNode }) {
  const { status } = useEmbedSession();
  if (status === 'loading') return <EmbedLoading />;
  if (status === 'expired') return <EmbedExpired />;
  return (
    <EmbedPortalRoot embedToken={embedAuthStore.getState()?.accessToken ?? null}>{children}</EmbedPortalRoot>
  );
}
