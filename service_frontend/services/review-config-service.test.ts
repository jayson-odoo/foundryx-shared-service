/**
 * Review-config service shape (AC-06-63) — the real service maps the api-client
 * request/response correctly: list filters/paginates, create POSTs the camelCase
 * payload, and `meta` normalizes raw answer facts into the RuleBuilder's RuleFact
 * shape (adds the source/sourceLabel grouping keys).
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReviewConfig, ReviewConfigMeta } from '@/types/review';

const apiFetch = vi.fn();
vi.mock('@/lib/api-client', () => ({
  apiFetch: (...args: unknown[]) => apiFetch(...args),
}));

// Import AFTER the mock so the real service binds the stubbed api-client.
import { realReviewConfigService } from './review-config-service.real';

function cfg(id: string, name: string): ReviewConfig {
  return {
    id,
    name,
    formId: 'f1',
    reviewFormId: 'f2',
    requiredReviewCount: 1,
    scoreFieldKey: null,
    windowStart: null,
    windowEnd: null,
    reviewStartStatusId: null,
    revisionsStatusId: null,
    acceptedStatusId: null,
    rejectedStatusId: null,
    isActive: true,
    roles: [],
    createdAt: '2026-06-21T00:00:00Z',
    updatedAt: '2026-06-21T00:00:00Z',
  };
}

afterEach(() => apiFetch.mockReset());

describe('realReviewConfigService', () => {
  it('list() fetches the config collection and search-filters + paginates client-side', async () => {
    apiFetch.mockResolvedValue({ data: [cfg('a', 'Alpha'), cfg('b', 'Beta')], total: 2 });
    const res = await realReviewConfigService.list({ page: 0, pageSize: 25, search: 'bet' });
    expect(apiFetch).toHaveBeenCalledWith('/reviews/configurations');
    expect(res.data.map((r) => r.id)).toEqual(['b']);
    expect(res.total).toBe(1);
  });

  it('create() POSTs the camelCase payload to /reviews/configurations', async () => {
    apiFetch.mockResolvedValue(cfg('new', 'New'));
    await realReviewConfigService.create({ name: 'New', formId: 'f1', reviewFormId: 'f2' });
    expect(apiFetch).toHaveBeenCalledWith(
      '/reviews/configurations',
      expect.objectContaining({ method: 'POST' }),
    );
    const body = JSON.parse((apiFetch.mock.calls[0][1] as { body: string }).body);
    expect(body).toMatchObject({ name: 'New', formId: 'f1', reviewFormId: 'f2' });
  });

  it('update() PATCHes the config by id', async () => {
    apiFetch.mockResolvedValue(cfg('a', 'Renamed'));
    await realReviewConfigService.update('a', { name: 'Renamed' });
    expect(apiFetch).toHaveBeenCalledWith(
      '/reviews/configurations/a',
      expect.objectContaining({ method: 'PATCH' }),
    );
  });

  it('meta() passes both form ids and normalizes facts to RuleFact shape', async () => {
    const raw: ReviewConfigMeta = {
      submissionStatuses: [{ id: 's1', label: 'In review', color: '#000' }],
      numericFields: [{ key: 'overall', label: 'Overall' }],
      // raw facts arrive WITHOUT source/sourceLabel.
      submissionFacts: [
        { key: 'answers.track', label: 'Track', type: 'enum' },
      ] as unknown as ReviewConfigMeta['submissionFacts'],
    };
    apiFetch.mockResolvedValue(raw);
    const meta = await realReviewConfigService.meta('f1', 'f2');
    expect(apiFetch).toHaveBeenCalledWith(
      '/reviews/configurations/form-meta?submissionFormId=f1&reviewFormId=f2',
    );
    expect(meta.submissionFacts[0]).toMatchObject({
      key: 'answers.track',
      type: 'enum',
      source: 'submission',
      sourceLabel: 'Submission answers',
    });
    expect(meta.submissionStatuses).toHaveLength(1);
    expect(meta.numericFields[0].key).toBe('overall');
  });
});
