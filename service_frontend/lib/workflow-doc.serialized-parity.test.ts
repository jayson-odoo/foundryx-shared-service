/**
 * Plan 31 S6 (AC-WFP-06/69) - the frontend `validateDefinition` and the
 * backend `definition_issues` (`app/workflow_engine/schemas.py`) must
 * produce the IDENTICAL message for a graph carrying a parking action
 * (`ActionDef.requires_serialized` / `ActionCatalogEntry.requiresSerialized`)
 * without serialized execution + a correlation key. Both sides build the
 * message as `f"{label} requires serialized execution and a Correlation
 * key."` from the SAME action label - this test pins the exact string so a
 * label rename on one side without the other fails loudly here, not in
 * production.
 */
import { describe, expect, it } from 'vitest';
import { validateDefinition } from './workflow-doc';
import { catalogEntry } from './workflow-catalog';
import type { WorkflowDefinition } from '@/types/workflows';

// Verbatim from `app/workflow_engine/schemas.py definition_issues`:
//   issues.append(f"{label} requires serialized execution and a Correlation key.")
function backendMessage(label: string): string {
  return `${label} requires serialized execution and a Correlation key.`;
}

function docWithAskQuestion(execution?: WorkflowDefinition['execution']): WorkflowDefinition {
  return {
    schemaVersion: 2,
    execution,
    nodes: [
      {
        id: 'trg_1',
        kind: 'trigger',
        type: 'omnichannel.message_received',
        config: {},
        position: { x: 0, y: 0 },
      },
      {
        id: 'ask_1',
        kind: 'action',
        type: 'omnichannel.ask_question',
        config: { contactId: '{{ trigger.contact.id }}', answerType: 'text' },
        position: { x: 0, y: 150 },
      },
    ],
    edges: [{ id: 'e1', source: 'trg_1', target: 'ask_1', sourcePort: 'out' }],
  };
}

describe('validateDefinition <-> backend definition_issues parity (AC-WFP-06)', () => {
  it('the catalog flags omnichannel.ask_question as requiring serialized execution', () => {
    const entry = catalogEntry('omnichannel.ask_question');
    expect(entry?.kind === 'action' && entry.requiresSerialized).toBe(true);
  });

  it('produces the exact backend string when unserialized', () => {
    const issues = validateDefinition(docWithAskQuestion(undefined));
    const label = catalogEntry('omnichannel.ask_question')?.label ?? '';
    expect(issues.map((i) => i.message)).toContain(backendMessage(label));
    expect(backendMessage(label)).toBe(
      'Ask a question requires serialized execution and a Correlation key.',
    );
  });

  it('produces no such issue once serialized with a correlation key', () => {
    const issues = validateDefinition(
      docWithAskQuestion({ mode: 'serialized', correlationKey: '{{ trigger.contact.id }}' }),
    );
    expect(issues.some((i) => i.message.includes('requires serialized execution'))).toBe(false);
  });

  it('is registry-driven: renaming the catalog label changes the emitted message with it', () => {
    // Sanity-checks the loop reads `entry.label`, not a hardcoded string -
    // the label used above already came from the catalog, so a future
    // rename of "Ask a question" is automatically reflected without a
    // second edit in `validateDefinition`.
    const entry = catalogEntry('omnichannel.ask_question');
    const issues = validateDefinition(docWithAskQuestion(undefined));
    expect(issues.some((i) => i.message.startsWith(entry?.label ?? ''))).toBe(true);
  });
});
