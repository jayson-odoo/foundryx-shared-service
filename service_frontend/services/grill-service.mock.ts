/**
 * Mock grill service (Phase B-i slice 3) — an in-memory grill for frontend-first
 * builds + Vitest. NOT wired into the app (the boundary in `grill-service.ts`
 * points at `.real`); retained for tests only.
 *
 * It fakes the model with a deterministic script: each turn acknowledges the
 * message and marks one more target field covered, so the coverage indicator and
 * the "offer to generate" state can be exercised with no backend.
 */
import type { GrillGenerate, GrillState, GrillTurn } from '@/types/grill';
import type { GrillService } from './grill-service';

const FIELDS = [
  { key: 'problem_statement', label: 'Problem statement' },
  { key: 'business_goal', label: 'Business goal' },
  { key: 'stakeholders', label: 'Stakeholders' },
  { key: 'success_metric', label: 'Success metric' },
  { key: 'scope', label: 'Scope' },
  { key: 'constraints', label: 'Constraints' },
];

interface MockRun {
  messages: GrillState['messages'];
  covered: string[];
}

export function createMockGrillService(
  overrides: Partial<GrillService> & { ready?: boolean } = {},
): GrillService {
  const runs = new Map<string, MockRun>();
  const ready = overrides.ready ?? true;

  function run(brId: string): MockRun {
    let r = runs.get(brId);
    if (!r) {
      r = { messages: [], covered: [] };
      runs.set(brId, r);
    }
    return r;
  }

  const base: GrillService = {
    async state(brId): Promise<GrillState> {
      const r = run(brId);
      return {
        ready,
        warning: ready ? null : 'No AI connection configured.',
        agentName: 'Ideation grill',
        fields: FIELDS,
        messages: r.messages,
        coveredFields: r.covered,
      };
    },

    async turn(brId, message): Promise<GrillTurn> {
      const r = run(brId);
      const now = new Date().toISOString();
      r.messages.push({
        id: `u-${r.messages.length}`,
        role: 'user',
        content: message,
        coveredFields: [],
        createdAt: now,
      });
      const next = FIELDS.find((f) => !r.covered.includes(f.key));
      if (next) r.covered = [...r.covered, next.key];
      const remaining = FIELDS.filter((f) => !r.covered.includes(f.key));
      const reply = remaining.length
        ? `Got it. What about ${remaining[0].label.toLowerCase()}?`
        : 'That covers everything — you can generate the requirement now.';
      r.messages.push({
        id: `a-${r.messages.length}`,
        role: 'assistant',
        content: reply,
        coveredFields: r.covered,
        createdAt: now,
      });
      return { replyText: reply, coveredFields: r.covered };
    },

    async generate(): Promise<GrillGenerate> {
      return { status: 'ok', br: null, answers: {}, fieldErrors: {} };
    },
  };

  return { ...base, ...overrides };
}

export const mockGrillService: GrillService = createMockGrillService();
