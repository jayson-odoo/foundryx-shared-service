/**
 * In-memory AI prompt registry service - Phase 1 fixture (Meetings S4 plan
 * §3.4). Wired into `ai-prompts-service.ts` until Phase 2 lands the real
 * routes (`ai-prompts-service.real.ts`) and the swap happens there; also
 * importable directly by tests.
 */
import type {
  AiPromptDetail,
  AiPromptSummary,
  AiPromptVersion,
  CreatePromptVersionInput,
  PublishPromptVersionInput,
} from '@/types/ai-prompt';
import type { AiPromptsService } from './ai-prompts-service';

const NETWORK_DELAY_MS = 150;

function delay<T>(value: T): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), NETWORK_DELAY_MS));
}

function nowIso(): string {
  return new Date().toISOString();
}

const MEETINGS_MINUTES_TEMPLATE_V1 = `You are taking minutes for a meeting titled "{{title}}".

Participants: {{participants}}

Write the minutes in {{language}}. Use only what is said in the transcript below -
never invent a decision or an action item.

Transcript:
{{transcript}}

Return JSON with exactly these keys: summary, decisions, action_items,
open_questions, topic_notes.`;

const MEETINGS_MINUTES_TEMPLATE_V2 = `You are the minute-taker for "{{title}}".

Participants: {{participants}}
Output language: {{language}}

Read the transcript below and produce structured minutes. Ground every
sentence in what was actually said - no inference, no invented decisions.

Transcript:
{{transcript}}

Respond with JSON: summary, decisions, action_items, open_questions,
topic_notes.`;

interface PromptStoreEntry {
  name: string;
  variables: string[];
  labels: { production: number | null; staging: number | null };
  versions: AiPromptVersion[];
}

const store = new Map<string, PromptStoreEntry>([
  [
    'meetings_minutes',
    {
      name: 'meetings_minutes',
      variables: ['title', 'participants', 'language', 'transcript'],
      labels: { production: 2, staging: null },
      versions: [
        {
          id: 'promptver-2',
          version: 2,
          template: MEETINGS_MINUTES_TEMPLATE_V2,
          commitMessage: 'Tighten grounding instructions after a hallucinated action item.',
          createdByName: 'Wei Ling',
          createdAt: '2026-08-30T03:12:00.000Z',
          labels: ['production'],
        },
        {
          id: 'promptver-1',
          version: 1,
          template: MEETINGS_MINUTES_TEMPLATE_V1,
          commitMessage: 'Initial minutes prompt.',
          createdByName: 'Wei Ling',
          createdAt: '2026-08-20T09:00:00.000Z',
          labels: [],
        },
      ],
    },
  ],
]);

function toSummary(entry: PromptStoreEntry): AiPromptSummary {
  const latest = entry.versions[0] ?? null;
  return {
    name: entry.name,
    productionVersion: entry.labels.production,
    latestVersion: latest?.version ?? null,
    updatedAt: latest?.createdAt ?? null,
    updatedByName: latest?.createdByName ?? null,
  };
}

function toDetail(entry: PromptStoreEntry): AiPromptDetail {
  return {
    name: entry.name,
    variables: [...entry.variables],
    labels: { ...entry.labels },
    versions: entry.versions.map((v) => ({ ...v, labels: [...v.labels] })),
  };
}

function requireEntry(name: string): PromptStoreEntry {
  const entry = store.get(name);
  if (!entry) throw new Error(`Prompt "${name}" not found`);
  return entry;
}

export const mockAiPromptsService: AiPromptsService = {
  listPrompts: async () => delay(Array.from(store.values()).map(toSummary)),

  getPrompt: async (name) => {
    const entry = store.get(name);
    return delay(entry ? toDetail(entry) : null);
  },

  createVersion: async (name, input: CreatePromptVersionInput) => {
    const entry = requireEntry(name);
    const nextVersion = (entry.versions[0]?.version ?? 0) + 1;
    const created: AiPromptVersion = {
      id: `promptver-${name}-${nextVersion}`,
      version: nextVersion,
      template: input.template,
      commitMessage: input.commitMessage,
      createdByName: 'You',
      createdAt: nowIso(),
      labels: [],
    };
    entry.versions = [created, ...entry.versions];
    return delay({ ...created, labels: [...created.labels] });
  },

  publishVersion: async (name, input: PublishPromptVersionInput) => {
    const entry = requireEntry(name);
    const target = entry.versions.find((v) => v.id === input.versionId);
    if (!target) throw new Error('Version not found');
    // Move the label: strip it off whichever version held it, stamp the new one.
    for (const v of entry.versions) {
      v.labels = v.labels.filter((l) => l !== input.label);
    }
    target.labels = [...target.labels, input.label];
    entry.labels[input.label] = target.version;
    return delay(toDetail(entry));
  },
};
