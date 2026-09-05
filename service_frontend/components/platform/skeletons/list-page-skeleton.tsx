import { Container } from '@/components/common/container';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

export interface ListPageSkeletonProps {
  /** How many row bars to draw. Ten is a page of a busy list. */
  rows?: number;
}

/**
 * What a `ResourceList`/`DataGrid` route shows between the click and the
 * rows (AC-DLA-48). Rendered by a route's `loading.tsx` INSIDE
 * `app/(protected)/layout.tsx`, so the sidebar/header/crumb chrome stays put
 * and only the content pane changes.
 *
 * Deliberately generic - a crumb bar, the title row, a toolbar bar, a header
 * row (darker, like a real grid header), and `rows` body bars sized to the
 * shell's actual 60px row height. A skeleton that tried to match each
 * list's own columns would be a second copy of that list's layout, kept in
 * step by hand, to be looked at for a few hundred milliseconds.
 */
export function ListPageSkeleton({ rows = 8 }: ListPageSkeletonProps) {
  return (
    <div data-skeleton="list">
      <Container width="fluid">
        {/* Crumb bar above the title (D6 - PageHeader always renders crumbs
            above the h1). */}
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
          <CardHeader className="flex items-center justify-between gap-3">
            {/* T6 fix round 1 item 10: h-8.5, matching Input variant="md"
                (components/ui/input.tsx) - the real ListSearchInput this
                stands in for renders at that height. */}
            <Skeleton className="h-8.5 w-64" />
            <div className="flex items-center gap-2">
              <Skeleton className="h-9 w-24" />
              <Skeleton className="h-9 w-9" />
            </div>
          </CardHeader>
          <CardContent className="p-0">
            {/* T6 fix round 1 item 10: h-10, matching the real DataGrid
                header cell height (components/ui/data-grid-table.tsx, the
                `relative h-10` header <th> class) - was h-11. */}
            <div className="flex h-10 items-center gap-4 border-b border-border px-5">
              <Skeleton className="h-4 w-4 shrink-0" />
              <Skeleton className="h-3.5 w-32" />
              <Skeleton className="h-3.5 w-24" />
              <Skeleton className="hidden h-3.5 w-28 sm:block" />
              <Skeleton className="hidden h-3.5 w-20 lg:block" />
              <Skeleton className="ms-auto h-3.5 w-16" />
            </div>
            {Array.from({ length: rows }).map((_, index) => (
              <div
                key={index}
                // 60px to match the DataGrid body row height - there is no
                // shared height constant/token for it (data-grid-table.tsx's
                // body cells size off `px-4 py-3` padding + content, not a
                // fixed literal), so this is a measured approximation, kept
                // in sync by eye against the real grid.
                className="flex h-[60px] items-center gap-4 border-b border-border px-5 last:border-b-0"
              >
                <Skeleton className="h-4 w-4 shrink-0" />
                <Skeleton className="h-3.5 w-40" />
                <Skeleton className="h-3.5 w-20" />
                <Skeleton className="hidden h-3.5 w-32 sm:block" />
                <Skeleton className="hidden h-3.5 w-16 lg:block" />
                <Skeleton className="ms-auto h-3.5 w-8" />
              </div>
            ))}
            {/* Pagination strip placeholder. */}
            <div className="flex items-center justify-between px-5 py-3">
              <Skeleton className="h-3.5 w-28" />
              <div className="flex items-center gap-1.5">
                <Skeleton className="h-8 w-8" />
                <Skeleton className="h-8 w-8" />
                <Skeleton className="h-8 w-8" />
              </div>
            </div>
          </CardContent>
        </Card>
      </Container>
    </div>
  );
}
