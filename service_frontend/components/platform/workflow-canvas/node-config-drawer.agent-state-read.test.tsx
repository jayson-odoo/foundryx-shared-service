import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { WorkflowDefinition } from '@/types/workflows';
import { NodeConfigDrawer, readStateOutputParams } from './node-config-drawer';

const BASE_METADATA = { entities: [] };

/** Plan sprint-4/20 - the read node's dynamic outputs (AC-ASR-03/04). */

function readNode(agentNodeId: string): WorkflowDefinition {
  return {
    schemaVersion: 1,
    nodes: [
      { id: 'trg', kind: 'trigger', type: 'manual', config: { inputs: [] }, position: { x: 0, y: 0 } },
      {
        id: 'ai_1',
        kind: 'action',
        type: 'ai_agent.run',
        config: {
          agentId: 'a',
          outputParams: [
            { key: 'task', type: 'string', stateful: true },
            { key: 'status', type: 'string', stateful: true },
            { key: 'reply', type: 'string' }, // transient - NOT state
          ],
        },
        position: { x: 0, y: 100 },
      },
      {
        id: 'read_1',
        kind: 'action',
        type: 'ai_agent.read_state',
        config: { agentNodeId },
        position: { x: 0, y: 200 },
      },
    ],
    edges: [
      { id: 'e1', source: 'trg', target: 'ai_1', sourcePort: 'out' },
      { id: 'e2', source: 'ai_1', target: 'read_1', sourcePort: 'out' },
    ],
  };
}

describe('readStateOutputParams', () => {
  it('exposes the selected agent stateful fields + reserved diagnostics (AC-ASR-03)', () => {
    const doc = readNode('ai_1');
    const read = doc.nodes.find((n) => n.id === 'read_1')!;
    const keys = readStateOutputParams(read, doc).map((p) => p.key);
    expect(keys).toEqual(['task', 'status', 'stateRevision', 'pendingField', 'exists']);
    // transient outputs are not state and must not appear
    expect(keys).not.toContain('reply');
    const exists = readStateOutputParams(read, doc).find((p) => p.key === 'exists');
    expect(exists?.type).toBe('boolean');
    const rev = readStateOutputParams(read, doc).find((p) => p.key === 'stateRevision');
    expect(rev?.type).toBe('number');
  });

  it('exposes only the diagnostics when no agent is selected (AC-ASR-04)', () => {
    const doc = readNode('');
    const read = doc.nodes.find((n) => n.id === 'read_1')!;
    expect(readStateOutputParams(read, doc).map((p) => p.key)).toEqual([
      'stateRevision',
      'pendingField',
      'exists',
    ]);
  });

  it('returns nothing for a non-read node', () => {
    const doc = readNode('ai_1');
    expect(readStateOutputParams(doc.nodes.find((n) => n.id === 'ai_1')!, doc)).toEqual([]);
  });

  it('drops the reserved diagnostic key from a same-named stateful field (dedup)', () => {
    const doc = readNode('ai_1');
    const ai = doc.nodes.find((n) => n.id === 'ai_1')!;
    ai.config = {
      ...ai.config,
      outputParams: [
        { key: 'task', type: 'string', stateful: true },
        { key: 'exists', type: 'string', stateful: true },
      ],
    };
    const read = doc.nodes.find((n) => n.id === 'read_1')!;
    const params = readStateOutputParams(read, doc);
    const keys = params.map((p) => p.key);
    // 'exists' appears exactly once, and it's the reserved boolean diagnostic
    // (reserved wins over a same-named accepted field, matching the backend).
    expect(keys.filter((k) => k === 'exists')).toHaveLength(1);
    expect(params.find((p) => p.key === 'exists')?.type).toBe('boolean');
    expect(keys).toEqual(['task', 'stateRevision', 'pendingField', 'exists']);
  });
});

describe('NodeConfigDrawer - agentNode picker warning (AC-ASR-02)', () => {
  it('warns when no upstream stateful AI Agent is reachable', () => {
    const doc: WorkflowDefinition = {
      schemaVersion: 1,
      nodes: [
        { id: 'trg', kind: 'trigger', type: 'manual', config: { inputs: [] }, position: { x: 0, y: 0 } },
        { id: 'read_1', kind: 'action', type: 'ai_agent.read_state', config: { agentNodeId: '' }, position: { x: 0, y: 100 } },
      ],
      edges: [{ id: 'e1', source: 'trg', target: 'read_1', sourcePort: 'out' }],
    };
    render(
      <NodeConfigDrawer
        node={doc.nodes[1]}
        doc={doc}
        editing
        templateOptions={[]}
        metadata={BASE_METADATA}
        onConfigChange={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(screen.getByTestId('agent-node-warning')).toBeInTheDocument();
    expect(screen.getByText('Add a stateful AI Agent upstream first.')).toBeInTheDocument();
  });

  it('does not warn once a stateful AI Agent is reachable upstream', () => {
    const doc = readNode('ai_1');
    const read = doc.nodes.find((n) => n.id === 'read_1')!;
    render(
      <NodeConfigDrawer
        node={read}
        doc={doc}
        editing
        templateOptions={[]}
        metadata={BASE_METADATA}
        onConfigChange={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(screen.queryByTestId('agent-node-warning')).not.toBeInTheDocument();
  });
});
