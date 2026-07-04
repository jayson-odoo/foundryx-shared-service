'use client';

/** Ordered submission ids for prev/next scroll-through (Resource-shell-style
 * record nav). Fetched once per form; the same default order as the list
 * (current revision per group — plan sprint-4/04 R3). */
import { useEffect, useState } from 'react';
import { formService } from '@/services/form-service';

export function useSubmissionNav(formId: string, submissionId: string) {
  const [ids, setIds] = useState<string[]>([]);
  useEffect(() => {
    let cancelled = false;
    formService
      .submissions(formId, { page: 0, pageSize: 200 })
      .then((res) => !cancelled && setIds(res.data.map((r) => r.id)))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [formId]);
  const index = ids.indexOf(submissionId);
  return {
    index,
    total: ids.length,
    prevId: index > 0 ? ids[index - 1] : null,
    nextId: index >= 0 && index < ids.length - 1 ? ids[index + 1] : null,
  };
}
