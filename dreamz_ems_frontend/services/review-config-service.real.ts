/**
 * Real Review-config service — talks to the core `/reviews` router via the
 * shared api-client (plan sprint-4/06 slice 1). The submission-fact metadata is
 * normalized to the RuleBuilder's `RuleFact` shape (the backend returns the
 * answer facts without the `source`/`sourceLabel` the builder groups by).
 */
import { apiFetch } from '@/lib/api-client';
import type { ListQuery, ListResult } from '@/types/resource';
import type {
  ReviewAdminSubmission,
  ReviewConfig,
  ReviewConfigCreateInput,
  ReviewConfigListResult,
  ReviewConfigMeta,
  ReviewConfigUpdateInput,
} from '@/types/review';
import type { RuleFact } from '@/types/rules';
import type { ReviewConfigService } from './review-config-service';

const SUBMISSION_FACT_SOURCE = 'submission';
const SUBMISSION_FACT_SOURCE_LABEL = 'Submission answers';

/** Raw metadata facts carry no source — group them under one "Submission" source
 * so the RuleBuilder's grouped picker has a heading. */
function normalizeFacts(raw: ReviewConfigMeta['submissionFacts']): RuleFact[] {
  return (raw as unknown as Omit<RuleFact, 'source' | 'sourceLabel'>[]).map((f) => ({
    ...f,
    source: SUBMISSION_FACT_SOURCE,
    sourceLabel: SUBMISSION_FACT_SOURCE_LABEL,
  }));
}

export const realReviewConfigService: ReviewConfigService = {
  async list(query: ListQuery): Promise<ListResult<ReviewConfig>> {
    const res = await apiFetch<ReviewConfigListResult>('/reviews/configurations');
    const search = (query.search ?? '').trim().toLowerCase();
    let rows = res.data;
    if (search) {
      rows = rows.filter((r) => r.name.toLowerCase().includes(search));
    }
    if (query.sort) {
      const { id, desc } = query.sort;
      rows = [...rows].sort((a, b) => {
        const av = String((a as unknown as Record<string, unknown>)[id] ?? '');
        const bv = String((b as unknown as Record<string, unknown>)[id] ?? '');
        return desc ? bv.localeCompare(av) : av.localeCompare(bv);
      });
    }
    const total = rows.length;
    const start = query.page * query.pageSize;
    return { data: rows.slice(start, start + query.pageSize), total, page: query.page };
  },

  get(id: string): Promise<ReviewConfig | null> {
    return apiFetch<ReviewConfig>(`/reviews/configurations/${id}`).catch(() => null);
  },

  create(payload: ReviewConfigCreateInput): Promise<ReviewConfig> {
    return apiFetch<ReviewConfig>('/reviews/configurations', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  update(id: string, payload: ReviewConfigUpdateInput): Promise<ReviewConfig> {
    return apiFetch<ReviewConfig>(`/reviews/configurations/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  },

  remove(id: string): Promise<void> {
    return apiFetch<void>(`/reviews/configurations/${id}`, { method: 'DELETE' });
  },

  async meta(submissionFormId, reviewFormId): Promise<ReviewConfigMeta> {
    const sp = new URLSearchParams();
    if (submissionFormId) sp.set('submissionFormId', submissionFormId);
    if (reviewFormId) sp.set('reviewFormId', reviewFormId);
    const q = sp.toString();
    const res = await apiFetch<ReviewConfigMeta>(
      `/reviews/configurations/form-meta${q ? `?${q}` : ''}`,
    );
    return { ...res, submissionFacts: normalizeFacts(res.submissionFacts) };
  },

  adminSubmissions(configId: string): Promise<ReviewAdminSubmission[]> {
    return apiFetch<ReviewAdminSubmission[]>(
      `/reviews/configurations/${configId}/submissions`,
    );
  },
};
