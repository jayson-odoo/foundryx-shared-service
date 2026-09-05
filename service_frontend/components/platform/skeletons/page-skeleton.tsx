import { Container } from '@/components/common/container';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

/**
 * Neutral fallback for `app/(protected)/loading.tsx` (the GROUP ROOT), shown
 * while a segment's own chunk loads when that segment has no more specific
 * `loading.tsx` of its own (a custom page - not a `ResourceList`/`DataGrid`
 * list and not a `ResourceForm` record - e.g. settings/general,
 * settings/branding, omnichannel/inbox, forms/[id]/fill, imports, jobs/[id],
 * documents, platform/rules). AC-DLA-48 fix round 1 item 1: this used to be
 * `ListPageSkeleton`, which drew a grid + pagination strip on every one of
 * these non-list pages, then swapped to a completely different layout once
 * the real page mounted.
 *
 * Deliberately minimal: a title block sized like `PageHeader` (crumb line +
 * title + description line) and ONE section card - no row bars, no
 * pagination strip. `ListPageSkeleton` and `RecordPageSkeleton` stay
 * strictly scoped to their own list/record segments; this is the one
 * skeleton every OTHER segment shape can plausibly settle into without
 * looking wrong for a few hundred milliseconds.
 */
export function PageSkeleton() {
  return (
    <div data-skeleton="page">
      <Container width="fluid">
        {/* Crumb bar above the title (D6 - PageHeader always renders crumbs
            above the h1), same sizing as ListPageSkeleton/RecordPageSkeleton. */}
        <Skeleton className="mb-2 h-4 w-40" />
        <div className="flex flex-wrap items-center justify-between gap-3 pb-5">
          <div className="space-y-2">
            <Skeleton className="h-6 w-56" />
            <Skeleton className="h-3.5 w-72" />
          </div>
          <Skeleton className="h-9 w-32" />
        </div>
      </Container>

      <Container width="fluid">
        <Card>
          <CardHeader>
            <Skeleton className="h-4 w-40" />
          </CardHeader>
          <CardContent className="space-y-3">
            <Skeleton className="h-3.5 w-full" />
            <Skeleton className="h-3.5 w-5/6" />
            <Skeleton className="h-3.5 w-2/3" />
          </CardContent>
        </Card>
      </Container>
    </div>
  );
}
