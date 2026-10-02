import { describe, expect, it } from 'vitest';
import { createNode } from '@/lib/workflow-doc';
import { mockWorkflowService } from './workflow-service.mock';

describe('mockWorkflowService', () => {
  it('provides deterministic safe sources for workflow test options', async () => {
    await expect(
      mockWorkflowService.getTestOptions('wf-welcome'),
    ).resolves.toEqual({
      omnichannelTestSources: [
        {
          channelId: 'chn-demo',
          channelName: 'Demo sandbox',
          contactId: 'cnt-001',
          contactName: 'Alice',
          contactPhone: '+6012',
        },
      ],
    });
  });

  it('returns state, Redis, and Code trace outputs from a mock run', async () => {
    const trigger = {
      ...createNode('manual', { x: 0, y: 0 }),
      id: 'trace-trigger',
    };
    const agent = {
      ...createNode('ai_agent.run', { x: 0, y: 100 }),
      id: 'trace-agent',
      config: {
        ...createNode('ai_agent.run', { x: 0, y: 100 }).config,
        agentId: 'agent-1',
        instructions: 'Classify',
        inputText: 'Input',
        outputParams: [
          { key: 'intent', type: 'string' as const, stateful: true },
        ],
      },
    };
    const clear = {
      ...createNode('ai_agent.clear_state', { x: 0, y: 200 }),
      id: 'trace-clear',
      config: { agentNodeId: agent.id },
    };
    const redis = {
      ...createNode('redis.command', { x: 0, y: 300 }),
      id: 'trace-redis',
      config: { operation: 'set', key: 'trace', value: 'value' },
    };
    const code = {
      ...createNode('code.run', { x: 0, y: 400 }),
      id: 'trace-code',
      config: {
        language: 'python',
        source: 'result = {}',
        inputs: [],
        outputs: [{ key: 'summary', type: 'string' as const }],
      },
    };
    const definition = {
      schemaVersion: 2,
      nodes: [trigger, agent, clear, redis, code],
      edges: [
        {
          id: 'trace-e1',
          source: trigger.id,
          target: agent.id,
          sourcePort: 'out',
        },
        {
          id: 'trace-e2',
          source: agent.id,
          target: clear.id,
          sourcePort: 'out',
        },
        {
          id: 'trace-e3',
          source: clear.id,
          target: redis.id,
          sourcePort: 'out',
        },
        {
          id: 'trace-e4',
          source: redis.id,
          target: code.id,
          sourcePort: 'out',
        },
      ],
    };
    const workflow = await mockWorkflowService.create({
      name: 'Trace test',
      description: '',
      draftDefinition: definition,
    });
    const run = await mockWorkflowService.run(workflow.id, { inputs: {} });
    const detail = await mockWorkflowService.getRun(run.id);
    expect(
      detail?.nodes.find((node) => node.nodeId === agent.id)?.outputJson,
    ).toMatchObject({
      stateRevision: 1,
      stateChangedFields: ['intent'],
    });
    expect(
      detail?.nodes.find((node) => node.nodeId === clear.id)?.outputJson,
    ).toMatchObject({ cleared: true });
    expect(
      detail?.nodes.find((node) => node.nodeId === redis.id)?.outputJson,
    ).toMatchObject({ stored: true });
    expect(
      detail?.nodes.find((node) => node.nodeId === code.id)?.outputJson,
    ).toMatchObject({ summary: 'mock output', terminationReason: 'completed' });
    await mockWorkflowService.remove(workflow.id);
  });

  it('rejects publishing a definition with invalid output parameters', async () => {
    const trigger = {
      ...createNode('manual', { x: 0, y: 0 }),
      id: 'invalid-trigger',
    };
    const agent = {
      ...createNode('ai_agent.run', { x: 0, y: 100 }),
      id: 'invalid-agent',
      config: {
        ...createNode('ai_agent.run', { x: 0, y: 100 }).config,
        agentId: 'agent-1',
        instructions: 'Classify',
        inputText: 'Input',
        outputParams: [{ key: '', type: 'string' as const }],
      },
    };
    const workflow = await mockWorkflowService.create({
      name: 'Invalid test',
      description: '',
      draftDefinition: {
        schemaVersion: 2,
        nodes: [trigger, agent],
        edges: [
          {
            id: 'invalid-e1',
            source: trigger.id,
            target: agent.id,
            sourcePort: 'out',
          },
        ],
      },
    });
    await expect(mockWorkflowService.publish(workflow.id)).rejects.toThrow(
      'without a key',
    );
    await mockWorkflowService.remove(workflow.id);
  });
});
