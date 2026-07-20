import { IdeasView } from '@/app/(protected)/ideation/ideas/ideas-view';
import { EmbedIdeationShell } from './embed-app';

/**
 * Chrome-less embed Ideas grid (WS-C / AC-CAP-9). OUTSIDE the `(protected)` group
 * — no app shell/nav, no NextAuth login redirect. The host (sorento) iframes
 * `{fe_base}/embed/ideas#token=<embed token>`; the credential arrives in the URL
 * fragment and is verified before any tenant data renders. Renders the SAME
 * {@link IdeasView} grid the operator page uses (one component, two modes), with
 * the FULL action set scoped to the connection's tenant + product server-side.
 */
export default function EmbedIdeasPage() {
  return (
    <EmbedIdeationShell>
      <div className="flex min-h-screen w-full flex-col gap-4 p-4 sm:p-6">
        <div className="flex flex-col gap-1">
          <h1 className="text-lg font-semibold text-foreground">Ideas</h1>
          <p className="text-sm text-muted-foreground">
            Ideas captured for your workspace — capture, vote, reprioritise and triage.
          </p>
        </div>
        <IdeasView />
      </div>
    </EmbedIdeationShell>
  );
}
