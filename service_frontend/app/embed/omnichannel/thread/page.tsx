import { EmbedShell } from '@/components/platform/omnichannel-embed';

/**
 * Chromeless embed thread route (sprint-4/11 AC-11H-12). Lives OUTSIDE the
 * `(protected)` group - no auth layout, no sidebar/header, no login redirect.
 * Boots bare and obtains its credential via the postMessage handshake (the
 * assertion is NEVER in the URL). CSP `frame-ancestors` is emitted by
 * `middleware.ts` from the connection's allowedOrigins, keyed on the non-secret
 * connection id the parent passes as `?c=<connectionId>` (AC-11H-15).
 */
export default function EmbedThreadPage() {
  return <EmbedShell mode="thread" />;
}
