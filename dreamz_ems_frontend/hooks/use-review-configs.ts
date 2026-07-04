'use client';

/**
 * Hooks for the standalone "Review processes" admin (plan sprint-4/06 slice 1):
 * a single loaded config, and the only-valid-option metadata (submission-form
 * scoped statuses + review-form numeric fields + submission answer facts) that
 * the pickers consume (AC-06-55). The list itself rides the Resource shell's
 * `useResourceList` via the service `list` fetcher — no separate hook needed.
 */
import { useCallback, useEffect, useState } from 'react';
import { reviewConfigService } from '@/services/review-config-service';
import type {
  ReviewAdminSubmission,
  ReviewConfig,
  ReviewConfigMeta,
} from '@/types/review';

export interface UseReviewConfigResult {
  config: ReviewConfig | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

/** Load one config by id (the detail form). */
export function useReviewConfig(id: string | null): UseReviewConfigResult {
  const [config, setConfig] = useState<ReviewConfig | null>(null);
  const [loading, setLoading] = useState(Boolean(id));
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    if (!id) {
      setConfig(null);
      setLoading(false);
      return;
    }
    let active = true;
    setLoading(true);
    setError(null);
    reviewConfigService
      .get(id)
      .then((c) => {
        if (active) setConfig(c);
      })
      .catch((e) => {
        if (active) setError(e instanceof Error ? e.message : 'Could not load.');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [id, nonce]);

  return { config, loading, error, reload };
}

export interface UseReviewSubmissionsResult {
  submissions: ReviewAdminSubmission[];
  loading: boolean;
  error: string | null;
  reload: () => void;
}

/**
 * The admin Submissions overview for a config (AC §10 deferred — the staff
 * god-view): every submission group → reviews/scores → decision. Read-only.
 */
export function useReviewSubmissions(
  configId: string | null,
): UseReviewSubmissionsResult {
  const [submissions, setSubmissions] = useState<ReviewAdminSubmission[]>([]);
  const [loading, setLoading] = useState(Boolean(configId));
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    if (!configId) {
      setSubmissions([]);
      setLoading(false);
      return;
    }
    let active = true;
    setLoading(true);
    setError(null);
    reviewConfigService
      .adminSubmissions(configId)
      .then((rows) => {
        if (active) setSubmissions(rows);
      })
      .catch((e) => {
        if (active) setError(e instanceof Error ? e.message : 'Could not load.');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [configId, nonce]);

  return { submissions, loading, error, reload };
}

export interface UseReviewMetaResult {
  meta: ReviewConfigMeta;
  loading: boolean;
}

const EMPTY_META: ReviewConfigMeta = {
  submissionStatuses: [],
  numericFields: [],
  submissionFacts: [],
};

/**
 * The picker universes for the currently-selected (submission form, review form)
 * pair. Re-fetches whenever either id changes — so the status-mapping selects
 * and the score-field select always reflect the chosen forms (AC-06-55).
 */
export function useReviewConfigMeta(
  submissionFormId: string | null,
  reviewFormId: string | null,
): UseReviewMetaResult {
  const [meta, setMeta] = useState<ReviewConfigMeta>(EMPTY_META);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!submissionFormId && !reviewFormId) {
      setMeta(EMPTY_META);
      return;
    }
    let active = true;
    setLoading(true);
    reviewConfigService
      .meta(submissionFormId, reviewFormId)
      .then((m) => {
        if (active) setMeta(m);
      })
      .catch(() => {
        if (active) setMeta(EMPTY_META);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [submissionFormId, reviewFormId]);

  return { meta, loading };
}
