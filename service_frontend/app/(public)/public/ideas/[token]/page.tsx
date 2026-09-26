'use client';

/**
 * Public (anonymous) idea-status page (S5 AC-1601/AC-1106/AC-1115, grown into
 * a full page by issue #90 W1, AC-90-110/111/112). Pre-auth, token-only access
 * (no login prompt) - the shell opts this path out of its own chrome
 * (`ownsChromePath`) so this page supplies its own branded header/footer.
 * Mobile-first: single column at ~375px, a two-column layout (content + a
 * sticky sidebar for the next-step + timeline) from `lg:` up. Never renders
 * problem/solution/impact/department beyond what the backend already decided
 * is safe to expose (AC-90-104's exact key-set pins the wire contract).
 */
import { useParams } from 'next/navigation';
import { AlertCircle, Loader2 } from 'lucide-react';
import { usePublicIdeaStatus } from '@/hooks/use-public-idea-status';
import { useTenantBranding } from '@/hooks/use-branding';
import { usePublicPageBranding } from '@/app/(public)/public-branded-shell';
import type { PublicBranding } from '@/types/branding';
import { PublicIdeaHeader } from './components/public-idea-header';
import { IdeaHero } from './components/idea-hero';
import { IdeaStatusTimeline } from './components/idea-status-timeline';
import { NextStepCallout } from './components/next-step-callout';
import { IdeaDetailSections } from './components/idea-detail-sections';
import { PublicIdeaFooter } from './components/public-idea-footer';

const UNBRANDED: PublicBranding = {
  isBranded: false,
  tenantName: null,
  appName: null,
  slogan: null,
  logoUrl: null,
  faviconUrl: null,
  illustrationUrl: null,
  tokens: null,
  version: 0,
};

export default function PublicIdeaStatusPage() {
  const params = useParams();
  const token = String(params.token);
  const { view, loading, notFound } = usePublicIdeaStatus(token);
  // Review fix S2 (issue #90): prefer the shell's SSR-seeded value (never
  // flashes Foundryx on a branded host, even before the client fetch
  // resolves) - `usePublicPageBranding()` is null only when this page is
  // rendered OUTSIDE `PublicBrandedShell` (unit tests), where the page's own
  // `useTenantBranding()` resolution is the only source available.
  const shellBranding = usePublicPageBranding();
  const { branding: liveBranding, isResolved } = useTenantBranding();
  const branding = shellBranding ?? (isResolved ? liveBranding : UNBRANDED);

  if (loading && !view) {
    return (
      <div className="flex min-h-full grow items-center justify-center py-24 text-muted-foreground">
        <Loader2 className="size-6 animate-spin" />
      </div>
    );
  }

  if (notFound || !view) {
    return (
      <div className="mx-auto flex w-full max-w-md flex-col gap-4 px-4">
        <div
          className="flex flex-col items-center gap-3 py-24 text-center"
          data-testid="idea-status-notfound"
        >
          <AlertCircle className="size-10 text-muted-foreground" />
          <p className="text-base font-medium">This link isn’t available.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-full grow flex-col">
      <PublicIdeaHeader productName={view.productName} />
      <main className="mx-auto flex w-full max-w-5xl flex-col gap-4 px-4 py-6 sm:px-6">
        {/*
          ONE instance of each section, explicitly placed - never a
          `lg:hidden`/`hidden lg:flex` duplicate pair (that would double every
          heading/label in the DOM, breaking a `getByText` that expects a
          single match, and the assistive-tech tree along with it). Mobile
          (no `lg:` grid-cols) falls through to plain single-column DOM order:
          hero, next step, timeline, sections. From `lg:` up, explicit
          `col-start`/`row-start` moves the SAME elements into a two-column
          layout (content left, a sticky next-step + timeline sidebar right).
        */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_20rem] lg:items-start lg:gap-6">
          <div className="lg:col-start-1 lg:row-start-1">
            <IdeaHero
              ideaNumber={view.ideaNumber}
              title={view.title}
              problem={view.problem}
              status={view.status}
              statusColor={view.statusColor}
              submitterFirstName={view.submitterFirstName}
              submittedAt={view.submittedAt}
              upvotes={view.upvotes}
            />
          </div>
          <div className="lg:col-start-2 lg:row-start-1">
            <NextStepCallout nextStep={view.nextStep} />
          </div>
          <div className="lg:sticky lg:top-6 lg:col-start-2 lg:row-start-2">
            <IdeaStatusTimeline timeline={view.timeline} />
          </div>
          <div className="lg:col-start-1 lg:row-start-2">
            <IdeaDetailSections
              problem={view.problem}
              proposedSolution={view.proposedSolution}
              impact={view.impact}
              department={view.department}
            />
          </div>
        </div>
      </main>
      <PublicIdeaFooter branding={branding} />
    </div>
  );
}
