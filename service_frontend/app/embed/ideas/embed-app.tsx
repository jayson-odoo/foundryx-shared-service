'use client';

import { useMemo, type ReactNode } from 'react';
import { IdeationRuntimeProvider, type IdeationRuntime } from '@/hooks/use-ideation-runtime';
import { ideationEmbedService } from '@/services/ideation-embed-service';
import { useEmbedSession, EmbedExpired, EmbedLoading } from './embed-session';

/**
 * Build the EMBED ideation runtime (WS-C1). Same shape as the operator default,
 * but wired to the `/embed/*` service + embed URLs. In-iframe navigation MUST
 * carry the `#token=…` fragment (the credential lives there, never a query/log —
 * AC-E-10), so every URL appends the current fragment.
 */
function buildEmbedRuntime(): IdeationRuntime {
  const hash = typeof window !== 'undefined' ? window.location.hash : '';
  const withHash = (p: string) => `${p}${hash}`;
  return {
    mode: 'embed',
    service: ideationEmbedService,
    paths: {
      listHref: withHash('/embed/ideas'),
      formHref: (id, opts) =>
        withHash(`/embed/ideas/${encodeURIComponent(id)}${opts?.edit ? '?edit=1' : ''}`),
      newHref: withHash('/embed/ideas/new'),
    },
  };
}

/**
 * Session-gated, chrome-less embed shell (AC-CAP-9/12). Validates the fragment
 * embed token, then renders `children` (the SHARED operator Ideas components)
 * under the embed ideation runtime — no app shell/nav. An absent/expired token
 * degrades to the clean "session expired" state (never the full app, never
 * another tenant).
 */
export function EmbedIdeationShell({ children }: { children: ReactNode }) {
  const { status } = useEmbedSession();
  const runtime = useMemo(buildEmbedRuntime, []);
  if (status === 'loading') return <EmbedLoading />;
  if (status === 'expired') return <EmbedExpired />;
  return <IdeationRuntimeProvider runtime={runtime}>{children}</IdeationRuntimeProvider>;
}
