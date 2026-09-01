/**
 * AI prompt registry service - real backend binding (Meetings S4 P2a).
 *
 * Routes: `app/api/v1/ai_prompts.py` on the backend, gated
 * `require_platform_permission("ai_prompts.manage")`. Response shapes match
 * `types/ai-prompt.ts` verbatim - no client-side field mapping needed.
 */
import { apiFetch } from '@/lib/api-client';
import type {
  AiPromptDetail,
  AiPromptSummary,
  AiPromptVersion,
  CreatePromptVersionInput,
  PublishPromptVersionInput,
} from '@/types/ai-prompt';
import type { AiPromptsService } from './ai-prompts-service';

export const realAiPromptsService: AiPromptsService = {
  listPrompts() {
    return apiFetch<AiPromptSummary[]>('/ai-prompts');
  },

  getPrompt(name) {
    return apiFetch<AiPromptDetail>(`/ai-prompts/${encodeURIComponent(name)}`).catch(() => null);
  },

  createVersion(name, input: CreatePromptVersionInput) {
    return apiFetch<AiPromptVersion>(`/ai-prompts/${encodeURIComponent(name)}/versions`, {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },

  publishVersion(name, input: PublishPromptVersionInput) {
    return apiFetch<AiPromptDetail>(`/ai-prompts/${encodeURIComponent(name)}/publish`, {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },
};
