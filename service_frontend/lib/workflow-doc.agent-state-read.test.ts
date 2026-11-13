import { describe, expect, it } from 'vitest';
import type { WorkflowDefinition } from '@/types/workflows';
import { catalogEntry } from './workflow-catalog';
import { createNode, validateDefinition } from './workflow-doc';

/**
 * Plan sprint-4/20 - read-only Agent State node (BL-SS-032).
 * AC-ASR-01/02/10.
 */

function doc(readAgentNodeId: string, agentStateful = true): WorkflowDefinition {
  return {
    schemaVersion: 1,
    execution: { mode: 'serialized', correlationKey: '{{ trigger.conversationId }}' },
    nodes: [
      { id: 'trg', kind: 'trigger', type: 'manual', config: { inputs: [] }, position: { x: 0, y: 0 } },
      {
        id: 'ai_1',
        kind: 'action',
        type: 'ai_agent.run',
        config: {
          agentId: 'a',
          instructions: 'x',
          inputText: '{{ trigger.input.t }}',
          outputParams: [
            { key: 'task', type: 'string', stateful: agentStateful, required: true },
            { key: 'status', type: 'string', stateful: agentStateful },
          ],
        },
        position: { x: 0, y: 100 },
      },
      {
        id: 'read_1',
        kind: 'action',
        type: 'ai_agent.read_state',
        config: { agentNodeId: readAgentNodeId },
        position: { x: 0, y: 200 },
      },
    ],
    edges: [
      { id: 'e1', source: 'trg', target: 'ai_1', sourcePort: 'out' },
      { id: 'e2', source: 'ai_1', target: 'read_1', sourcePort: 'out' },
    ],
  };
}

describe('Read Agent State node - catalog + validation', () => {
  it('is a core Actions node with a single agentNode field (AC-ASR-01/02)', () => {
    const entry = catalogEntry('ai_agent.read_state');
    expect(entry).toBeTruthy();
    expect(entry?.category).toBe('Actions');
    expect(entry?.module).toBeUndefined(); // core, no module gate
    expect(entry?.fields).toEqual([
      { key: 'agentNodeId', label: 'Agent', type: 'agentNode', required: true },
    ]);
    expect(createNode('ai_agent.read_state', { x: 0, y: 0 }).config).toEqual({
      agentNodeId: '',
    });
  });

  it('publishes when it references a stateful AI Agent in the graph', () => {
    expect(validateDefinition(doc('ai_1'))).toEqual([]);
  });

  it('blocks publish when no agent is selected (AC-ASR-10)', () => {
    const issues = validateDefinition(doc(''));
    expect(issues.some((i) => /Agent.*required|required/i.test(i.message))).toBe(true);
  });

  it('blocks publish when the referenced node is not a stateful agent (AC-ASR-10)', () => {
    const missing = validateDefinition(doc('nope'));
    expect(missing.some((i) => /stateful AI Agent/i.test(i.message))).toBe(true);
    const notStateful = validateDefinition(doc('ai_1', false));
    expect(notStateful.some((i) => /stateful AI Agent/i.test(i.message))).toBe(true);
  });
});
