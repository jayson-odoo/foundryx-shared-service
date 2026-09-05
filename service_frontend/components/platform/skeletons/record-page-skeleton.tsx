import { Container } from '@/components/common/container';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

/**
 * What a `ResourceForm` route (record detail/create) shows between the
 * click and the record (AC-DLA-48). Mirrors `ListPageSkeleton`'s reasoning -
 * generic, rendered inside the shell via `loading.tsx`: a toolbar row
 * (crumbs + title left, Back right - D5/D6), an identity block, a tab
 * strip, and two section cards standing in for whichever tab's content
 * loads first.
 */
export function RecordPageSkeleton() {
  return (
    <Container width="fluid">
      <div className="flex flex-wrap items-center justify-between gap-3 pb-5">
        <div className="space-y-2">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-6 w-56" />
        </div>
        <Skeleton className="h-9 w-24" />
      </div>

      <Card className="mb-5">
        <CardContent className="flex flex-wrap items-center gap-4 py-5">
          <Skeleton className="size-14 shrink-0 rounded-full" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-5 w-48" />
            <Skeleton className="h-3.5 w-64" />
          </div>
          <Skeleton className="h-9 w-28" />
        </CardContent>
      </Card>

      <div className="mb-5 flex items-center gap-1 border-b border-border">
        <Skeleton className="h-9 w-24" />
        <Skeleton className="h-9 w-24" />
        <Skeleton className="h-9 w-24" />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <Skeleton className="h-4 w-32" />
          </CardHeader>
          <CardContent className="space-y-3">
            <Skeleton className="h-3.5 w-full" />
            <Skeleton className="h-3.5 w-5/6" />
            <Skeleton className="h-3.5 w-2/3" />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <Skeleton className="h-4 w-32" />
          </CardHeader>
          <CardContent className="space-y-3">
            <Skeleton className="h-3.5 w-full" />
            <Skeleton className="h-3.5 w-5/6" />
            <Skeleton className="h-3.5 w-2/3" />
          </CardContent>
        </Card>
      </div>
    </Container>
  );
}
