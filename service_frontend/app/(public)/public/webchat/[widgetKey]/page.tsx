'use client';

/**
 * The web chat PANEL (plan 34 / A7b S4, AC-WEB-44). Lives under a LITERAL
 * `public/` path segment (R12) so it can never collide with a protected
 * dynamic route at build time - the `(public)` folder above it is a route
 * GROUP (invisible in the URL); this file's real path is
 * `/public/webchat/{widgetKey}`.
 *
 * No tenant slug anywhere on this path (D-A7B-25/F2) - the widget key alone
 * resolves the tenant, channel and branding, all server-side via the
 * session response `useVisitorChat` calls on mount.
 */
import { useParams } from 'next/navigation';
import { WebchatPanel } from '@/components/platform/webchat-panel';

export default function WebchatPanelPage() {
  const params = useParams();
  const widgetKey = String(params.widgetKey);
  return <WebchatPanel widgetKey={widgetKey} />;
}
