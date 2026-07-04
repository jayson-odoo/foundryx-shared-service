/**
 * Rule-engine service boundary (sprint-2/02). UI → hook → service →
 * lib/api-client → FastAPI. Phase A binds the mock; Phase B swaps to the
 * real api-client impl in ONE line (bottom of file).
 */
import type { ListQuery, ListResult } from '@/types/resource';
import type { RuleFact, RuleSiteRow } from '@/types/rules';
import { realRuleEngineService } from './rule-engine-service.real';

export interface RuleEngineService {
  /**
   * Whitelisted facts for the given sources (`actor`, `record:<entity>`) —
   * backend `GET /rule-facts?sources=` (authenticated-only, D13).
   */
  getFacts(sources: string[]): Promise<RuleFact[]>;
  /** Rule-site observability rows — backend `GET /rules` (gated rules.read, D12). */
  listRules(query: ListQuery): Promise<ListResult<RuleSiteRow>>;
}

// Phase B: real api-client. (Mock retained in rule-engine-service.mock.ts for tests.)
export const ruleEngineService: RuleEngineService = realRuleEngineService;
