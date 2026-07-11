import { EmbedShell } from '@/components/platform/omnichannel-embed';

/**
 * Chromeless embed inbox route (sprint-4/11 AC-11H-12). Full workspace inbox
 * (scope `inbox`), OUTSIDE the `(protected)` group — chromeless, no login
 * redirect. Credential arrives via the postMessage handshake.
 */
export default function EmbedInboxPage() {
  return <EmbedShell mode="inbox" />;
}
