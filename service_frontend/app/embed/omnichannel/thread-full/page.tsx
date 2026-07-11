import { EmbedShell } from '@/components/platform/omnichannel-embed';

/**
 * Chromeless embed FULL-thread route — the same `thread:<contactId>` scope as
 * `/embed/omnichannel/thread`, but the full conversation UI (contact header /
 * assign / lifecycle), not the compact composer-only pane. Lives OUTSIDE the
 * `(protected)` group — no auth layout, no sidebar/header, no login redirect.
 * Credential arrives via the postMessage handshake; CSP `frame-ancestors` is
 * emitted by `middleware.ts` from the connection's allowedOrigins.
 */
export default function EmbedThreadFullPage() {
  return <EmbedShell mode="thread-full" />;
}
