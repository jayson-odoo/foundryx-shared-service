/**
 * AI service boundary (Phase B-i slice 1). UI → hook → THIS → api-client.
 *
 * Built frontend-first against `ai-service.mock`, then swapped to the real
 * api-client implementation - the swap is the ONE line at the bottom of this
 * file. The mock is retained for Vitest only (a shipped mock behind a "done"
 * slice would be debt).
 */
import type { ListQuery, ListResult } from '@/types/resource';
import type {
  AiAgent,
  AiAgentInput,
  AiModelList,
  AiPrerequisite,
  AiSkill,
  AiSkillInput,
  AiSkillOption,
  AiSkillUpdate,
  AiSkillVersion,
  AiTrace,
  AiTraceDetail,
} from '@/types/ai';
import { realAiService } from './ai-service.real';

export interface AiService {
  // ── agents ────────────────────────────────────────────────────────────
  listAgents(query: ListQuery): Promise<ListResult<AiAgent>>;
  /** Record-nav: the row at `index` within the full result set of `query`. */
  getAgentAt(query: ListQuery, index: number): Promise<{ agent: AiAgent | null; total: number }>;
  getAgent(id: string): Promise<AiAgent | null>;
  createAgent(input: AiAgentInput): Promise<AiAgent>;
  updateAgent(id: string, input: AiAgentInput): Promise<AiAgent>;
  removeAgent(id: string): Promise<void>;
  exportAgents(query: ListQuery, columns: string[]): Promise<string>;

  /** AC-BI-11 - is any LLM connection configured, and which may an agent use? */
  getPrerequisite(): Promise<AiPrerequisite>;
  /** AC-BI-05 - live model list; falls back to a curated static list. */
  listModels(connectionId: string): Promise<AiModelList>;
  listSkillOptions(): Promise<AiSkillOption[]>;

  // ── skills ────────────────────────────────────────────────────────────
  listSkills(query: ListQuery): Promise<ListResult<AiSkill>>;
  getSkillAt(query: ListQuery, index: number): Promise<{ skill: AiSkill | null; total: number }>;
  getSkill(id: string): Promise<AiSkill | null>;
  createSkill(input: AiSkillInput): Promise<AiSkill>;
  /** A changed body mints a NEW immutable version + moves the active label. */
  updateSkill(id: string, input: AiSkillUpdate): Promise<AiSkill>;
  removeSkill(id: string): Promise<void>;
  listSkillVersions(skillId: string): Promise<AiSkillVersion[]>;
  /** Rollback = a LABEL MOVE. No content copy, no delete. */
  rollbackSkill(skillId: string, versionId: string): Promise<AiSkill>;
  exportSkills(query: ListQuery, columns: string[]): Promise<string>;

  // ── traces ────────────────────────────────────────────────────────────
  listTraces(query: ListQuery): Promise<ListResult<AiTrace>>;
  getTrace(id: string): Promise<AiTraceDetail | null>;
  flagTrace(id: string, flagged: boolean): Promise<AiTrace>;
  /** Traces have no bulk export endpoint - CSV is rendered client-side from a
   *  large page (the workflow-service precedent). Raw prompts/completions are
   *  deliberately NOT exported; the trace detail is where you read those. */
  exportTraces(query: ListQuery, columns: string[]): Promise<string>;
}

// Slice 1 ships REAL-bound (Definition-of-Done #1 - a surviving mock is debt).
// `mockAiService` remains importable for unit tests only.
export const aiService: AiService = realAiService;
