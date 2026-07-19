'use client';

import { useEffect, useState } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import { embedAuthStore } from '@/lib/embed-auth-store';
import { ideationEmbedService } from '@/services/ideation-embed-service';

/**
 * Embed-session gate (PLAN-ideation-embed-sso §9, AC-E-8/9). The short-lived
 * embed token arrives in the URL FRAGMENT (`#token=…`) — never a query param, so
 * it stays out of logs/Referer (AC-E-10). This hook:
 *
 *   1. reads the token from the fragment (client-only);
 *   2. places it in `embedAuthStore` so `lib/api-client` uses it as the Bearer;
 *   3. verifies it via `POST /embed/validate` → resolves the tenant scope.
 *
 * No token / invalid / expired → `expired` (a clean refresh state, never the full
 * app, never another tenant). The store is cleared on unmount so the credential
 * never lingers.
 */
export type EmbedSessionStatus = 'loading' | 'ready' | 'expired';

function readFragmentToken(): string | null {
  if (typeof window === 'undefined') return null;
  const hash = window.location.hash.startsWith('#')
    ? window.location.hash.slice(1)
    : window.location.hash;
  if (!hash) return null;
  const token = new URLSearchParams(hash).get('token');
  return token && token.trim() ? token.trim() : null;
}

export function useEmbedSession(): { status: EmbedSessionStatus; tenantId: string | null } {
  const [status, setStatus] = useState<EmbedSessionStatus>('loading');
  const [tenantId, setTenantId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const token = readFragmentToken();
    if (!token) {
      setStatus('expired');
      return;
    }
    // In-memory only (never localStorage) — api-client reads it as the Bearer.
    embedAuthStore.set({ accessToken: token, workspaceId: '', agentId: '' });
    ideationEmbedService
      .validateToken(token)
      .then((scope) => {
        if (cancelled) return;
        setTenantId(scope.tenant_id);
        setStatus('ready');
      })
      .catch(() => {
        if (cancelled) return;
        setStatus('expired');
      });
    return () => {
      cancelled = true;
      embedAuthStore.clear();
    };
  }, []);

  return { status, tenantId };
}

/** Chrome-less "session expired — refresh" state (AC-E-9). Never the full app. */
export function EmbedExpired() {
  return (
    <div className="flex min-h-screen w-full flex-col items-center justify-center gap-4 p-8 text-center">
      <div className="flex size-12 items-center justify-center rounded-full bg-muted">
        <AlertTriangle className="size-6 text-muted-foreground" aria-hidden />
      </div>
      <div className="space-y-1">
        <h1 className="text-lg font-semibold text-foreground">Session expired</h1>
        <p className="max-w-sm text-sm text-muted-foreground">
          This embedded workspace couldn&apos;t start a secure session, or it timed out.
          Refresh the page to reconnect.
        </p>
      </div>
      <button
        type="button"
        onClick={() => window.location.reload()}
        className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
      >
        <RefreshCw className="size-4" aria-hidden />
        Refresh
      </button>
    </div>
  );
}

/** Chrome-less loading state while the token is being verified. */
export function EmbedLoading() {
  return (
    <div className="flex min-h-screen w-full items-center justify-center p-8">
      <p className="text-sm text-muted-foreground">Loading ideas…</p>
    </div>
  );
}
