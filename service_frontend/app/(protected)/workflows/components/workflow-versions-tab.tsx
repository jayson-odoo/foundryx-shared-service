'use client';

/** Versions tab (plan sprint-2/08 D4) - paginated version history. Never embed
 * the full list in the workflow GET; page it (history grows unbounded). */
import { useCallback, useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { useDatetime } from '@/hooks/use-datetime';
import { workflowService } from '@/services/workflow-service';
import type { WorkflowVersionSummary } from '@/types/workflows';

const PAGE_SIZE = 20;

export interface WorkflowVersionsTabProps {
  workflowId: string;
  currentVersionId: string | null;
}

export function WorkflowVersionsTab({ workflowId, currentVersionId }: WorkflowVersionsTabProps) {
  const { formatDateTime } = useDatetime();
  const [rows, setRows] = useState<WorkflowVersionSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);

  const load = useCallback(
    (nextPage: number) => {
      setLoading(true);
      workflowService
        .listVersions(workflowId, { page: nextPage, pageSize: PAGE_SIZE })
        .then((result) => {
          setRows((prev) => (nextPage === 0 ? result.data : [...prev, ...result.data]));
          setTotal(result.total);
          setPage(nextPage);
        })
        .finally(() => setLoading(false));
    },
    [workflowId],
  );

  useEffect(() => {
    load(0);
  }, [load]);

  if (!loading && rows.length === 0) {
    return (
      <p className="py-12 text-center text-sm text-muted-foreground">
        No versions yet. Publish the workflow to create version 1.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2 py-2" data-testid="workflow-versions">
      <ul className="flex flex-col gap-1.5">
        {rows.map((v) => (
          <li
            key={v.id}
            className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm"
          >
            <span className="flex items-center gap-2 font-medium text-foreground">
              v{v.versionNumber}
              {currentVersionId === v.id && (
                <Badge variant="primary" appearance="light" size="sm">
                  current
                </Badge>
              )}
            </span>
            <span className="text-xs text-muted-foreground">
              {v.publishedByName} · {formatDateTime(v.publishedAt)}
            </span>
          </li>
        ))}
      </ul>
      {rows.length < total && (
        <Button
          variant="outline"
          size="sm"
          className="self-center"
          disabled={loading}
          onClick={() => load(page + 1)}
          data-testid="versions-load-more"
        >
          {loading ? 'Loading…' : `Load more (${total - rows.length})`}
        </Button>
      )}
    </div>
  );
}
