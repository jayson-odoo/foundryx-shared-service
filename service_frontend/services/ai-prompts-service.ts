/**
 * AI prompt registry service boundary (Meetings S4, R4/R5). UI → hook →
 * THIS → api-client.
 *
 * Phase 2a: wired to the real backend (`ai-prompts-service.real.ts`, the
 * core `ai_prompt_versions` / `ai_prompt_labels` routes). `ai-prompts-service
 * .mock` remains importable for the Phase 1 vitest files only - a surviving
 * mock behind a "done" slice would be debt.
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
