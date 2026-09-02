/**
 * AI prompt registry service boundary (Meetings S4, R4/R5). UI → hook →
 * THIS → api-client.
 *
 * Wired to the real backend (`ai-prompts-service.real.ts`, the core
 * `ai_prompt_versions` / `ai_prompt_labels` routes). No mock module exists
 * (P3 review, S5) - the two vitest files (`page.test.tsx`,
 * `prompt-detail-view.test.tsx`) `vi.mock` this module inline instead.
 */
import type {
  AiPromptDetail,
  AiPromptSummary,
  AiPromptVersion,
  CreatePromptVersionInput,
  PublishPromptVersionInput,
} from '@/types/ai-prompt';
import { realAiPromptsService } from './ai-prompts-service.real';

export interface AiPromptsService {
  listPrompts(): Promise<AiPromptSummary[]>;
  getPrompt(name: string): Promise<AiPromptDetail | null>;
  createVersion(name: string, input: CreatePromptVersionInput): Promise<AiPromptVersion>;
  publishVersion(name: string, input: PublishPromptVersionInput): Promise<AiPromptDetail>;
}

export const aiPromptsService: AiPromptsService = realAiPromptsService;
