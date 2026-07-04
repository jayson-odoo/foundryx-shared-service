/**
 * Real rule-engine service — talks to FastAPI via the shared api-client.
 * `GET /rule-facts` (authenticated) + `GET /rules` (rules.read), sprint-2/02.
 */
import type { ListQuery, ListResult } from '@/types/resource';
import type { RuleFact, RuleSiteRow } from '@/types/rules';
import { apiFetch } from '@/lib/api-client';
import type { RuleEngineService } from './rule-engine-service';

export const realRuleEngineService: RuleEngineService = {
  getFacts(sources: string[]): Promise<RuleFact[]> {
    const params = new URLSearchParams({ sources: sources.join(',') });
    return apiFetch<{ data: RuleFact[] }>(
      `/rule-facts?${params.toString()}`,
    ).then((response) => response.data);
  },
  listRules(query: ListQuery): Promise<ListResult<RuleSiteRow>> {
    const params = new URLSearchParams();
    params.set('page', String(query.page));
    params.set('pageSize', String(query.pageSize));
    if (query.search) params.set('search', query.search);
    if (query.sort) {
      params.set('sortField', query.sort.id);
      params.set('sortDir', query.sort.desc ? 'desc' : 'asc');
    }
    return apiFetch<ListResult<RuleSiteRow>>(`/rules?${params.toString()}`);
  },
};
