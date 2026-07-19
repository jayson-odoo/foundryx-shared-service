import { EmbedIdeasBoard } from './embed-ideas-board';

/**
 * Chrome-less embed Ideas board (PLAN-ideation-embed-sso §9, AC-E-8). OUTSIDE the
 * `(protected)` group — no app shell/nav, no NextAuth login redirect. The host
 * (sorento) iframes `{fe_base}/embed/ideas#token=<embed token>`; the credential
 * arrives in the URL fragment and is verified before any tenant data renders.
 */
export default function EmbedIdeasPage() {
  return <EmbedIdeasBoard />;
}
