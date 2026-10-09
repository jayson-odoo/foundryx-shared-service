'use client';

/**
 * Issue #90 W2 (AC-90-2xx): whether an active Business Requirement template is
 * configured. The "New business requirement" dialog reads this BEFORE
 * offering Create so a user never round-trips the `br_template_unavailable`
 * 422 in the common case. Resolves once on mount; a load failure degrades to
 * `active: true` (fail OPEN on a transient network error - the dialog still
 * catches a real 422 on submit) rather than blocking Create on a fetch hiccup.
 */
import { useEffect, useState } from 'react';
import { businessRequirementService } from '@/services/business-requirement-service';

export interface UseBrTemplateStatus {
  active: boolean;
  loading: boolean;
}

export function useBrTemplateStatus(): UseBrTemplateStatus {
  const [active, setActive] = useState(true);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const status = await businessRequirementService.templateStatus();
        if (!cancelled) setActive(status.active);
      } catch {
        if (!cancelled) setActive(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return { active, loading };
}
