'use client';

import { Fragment, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import type { ImportJob } from '@/types/import';
import { useDatetime } from '@/hooks/use-datetime';
import { useTerminology } from '@/hooks/use-terminology';
import { importService } from '@/services/import-service';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Container } from '@/components/common/container';
import { PageHeader } from '@/components/platform/page-header';

const STATUS_TONE: Record<
  string,
  'success' | 'destructive' | 'secondary' | 'primary'
> = {
  done: 'success',
  failed: 'destructive',
  validated: 'primary',
};

/**
 * Import history (sprint-3/09 D9) - the full job list. Gated forms.read?
 * No - any authenticated user reaching here; the engine's own jobs are scoped
 * server-side (own jobs unless imports.read_all). Title via Terminology.
 */
export default function ImportsHistoryPage() {
  const router = useRouter();
  const { formatDateTime } = useDatetime();
  const { labelPlural } = useTerminology();
  const [jobs, setJobs] = useState<ImportJob[] | null>(null);

  useEffect(() => {
    importService
      .list({ pageSize: 50 })
      .then((r) => setJobs(r.items))
      .catch(() => setJobs([]));
  }, []);

  return (
    <Fragment>
      <PageHeader
        title={labelPlural('import')}
        description="Bulk-import history across your workspace."
      />
      <Container width="fluid">
        <Card>
          <CardContent className="p-0">
            {jobs === null ? (
              <div className="space-y-3 p-5">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : jobs.length === 0 ? (
              <p className="text-muted-foreground p-8 text-center text-sm">
                No imports yet.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Entity</TableHead>
                      <TableHead>Mode</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Rows</TableHead>
                      <TableHead>Created</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {jobs.map((j) => (
                      <TableRow
                        key={j.id}
                        className="cursor-pointer"
                        onClick={() => router.push(`/imports/${j.id}`)}
                      >
                        <TableCell className="font-medium">
                          {j.entityType}
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {j.mode}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant={STATUS_TONE[j.status] ?? 'secondary'}
                            appearance="light"
                          >
                            {j.status}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          {j.validRows}/{j.totalRows}
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {formatDateTime(j.createdAt)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>
      </Container>
    </Fragment>
  );
}
