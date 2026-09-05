'use client';

/** Versions tab (plan sprint-3/01 D9) - paginated version history (own
 * endpoint; never embedded in the form GET - history grows unbounded). */
import { useCallback, useEffect, useState } from 'react';
import { LoaderCircleIcon } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useDatetime } from '@/hooks/use-datetime';
import { formService } from '@/services/form-service';
import type { FormVersionRow } from '@/types/forms';

const PAGE_SIZE = 20;

export interface FormVersionsTabProps {
  formId: string;
  currentVersionId: string | null;
}

export function FormVersionsTab({ formId, currentVersionId }: FormVersionsTabProps) {
  const { formatDateTime } = useDatetime();
  const [rows, setRows] = useState<FormVersionRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);

  const load = useCallback(
    (nextPage: number) => {
      setLoading(true);
      formService
        .versions(formId, nextPage, PAGE_SIZE)
        .then((result) => {
          setRows((prev) => (nextPage === 0 ? result.data : [...prev, ...result.data]));
          setTotal(result.total);
          setPage(nextPage);
        })
        .finally(() => setLoading(false));
    },
    [formId],
  );

  useEffect(() => {
    load(0);
  }, [load]);

  if (!loading && rows.length === 0) {
    return (
      <p className="py-12 text-center text-sm text-muted-foreground">
        No versions yet. Publish the form to create version 1.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2 py-2" data-testid="form-versions">
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
              {v.publishedByName} · {formatDateTime(v.createdAt)}
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
          {loading ? <LoaderCircleIcon className="size-4 animate-spin" /> : `Load more (${total - rows.length})`}
        </Button>
      )}
    </div>
  );
}
