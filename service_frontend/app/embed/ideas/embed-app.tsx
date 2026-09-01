'use client';

import { useMemo, type ReactNode } from 'react';
import { IdeationRuntimeProvider, type IdeationRuntime } from '@/hooks/use-ideation-runtime';
import { ideationEmbedService } from '@/services/ideation-embed-service';
import { useEmbedSession, EmbedExpired, EmbedLoading } from './embed-session';

/**
 * Build the EMBED ideation runtime (WS-C1). Same shape as the operator default,
 * but wired to the `/embed/*` service. The embed token arrives ONCE in the URL
 * fragment (`#token=…`, AC-E-10) and is held in-memory by the session gate; it is
 * DELIBERATELY NOT appended to in-iframe navigation URLs - the DataGrid appends
 * its own `?ctx=…` list-context to `formHref`, which would land AFTER the `#`
 * fragment and corrupt the token. Navigation uses plain paths; the session gate
 * reads the persisted token (store-first) on each route mount.
 */
function buildEmbedRuntime(): IdeationRuntime {
  return {
    mode: 'embed',
    service: ideationEmbedService,
    paths: {
      listHref: '/embed/ideas',
      formHref: (id, opts) =>
        `/embed/ideas/${encodeURIComponent(id)}${opts?.edit ? '?edit=1' : ''}`,
      newHref: '/embed/ideas/new',
    },
  };
}

/**
 * Session-gated, chrome-less embed shell (AC-CAP-9/12). Validates the fragment
 * embed token, then renders `children` (the SHARED operator Ideas components)
 * under the embed ideation runtime - no app shell/nav. An absent/expired token
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
