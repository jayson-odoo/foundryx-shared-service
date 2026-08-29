import { describe, expect, it } from 'vitest';
import type { WorkflowAiOutputParam, WorkflowDefinition } from '@/types/workflows';
import { createBlankDefinition, createNode, migrateWorkflowDefinition, validAiOutputParams, validateDefinition } from './workflow-doc';

function aiDoc(outputParams: unknown): WorkflowDefinition {
  return {
    schemaVersion: 1,
    nodes: [
      { id: 'trg_1', kind: 'trigger', type: 'manual', config: { inputs: [] }, position: { x: 0, y: 0 } },
      {
        id: 'ai_1',
        kind: 'action',
        type: 'ai_agent.run',
        config: {
          agentId: 'agent-1',
          instructions: 'Classify.',
          inputText: 'Message',
          outputParams: outputParams as WorkflowAiOutputParam[],
        },
        position: { x: 200, y: 0 },
      },
    ],
    edges: [{ id: 'e1', source: 'trg_1', target: 'ai_1', sourcePort: 'out' }],
  };
}

describe('createNode defaultConfig - omnichannel + AI Agent nodes (plan sprint-4/17)', () => {
  it('creates a schema-v2 document with parallel execution defaults', () => {
    expect(createBlankDefinition()).toMatchObject({
      schemaVersion: 2,
      execution: { mode: 'parallel', correlationKey: '' },
    });
  });

  it('migrates an old document without changing its graph', () => {
    const old = aiDoc([{ key: 'intent', type: 'string' }]);
    const migrated = migrateWorkflowDefinition(old);
    expect(migrated.schemaVersion).toBe(2);
    expect(migrated.execution).toEqual({ mode: 'parallel', correlationKey: '' });
    expect(migrated.nodes).toEqual(old.nodes);
    expect(migrated.edges).toEqual(old.edges);
  });

  it('seeds ai_agent.run with an empty output-params list', () => {
    const node = createNode('ai_agent.run', { x: 0, y: 0 });
    expect(node.kind).toBe('action');
    expect(node.config).toEqual({
      agentId: '',
      instructions: '',
      inputText: '',
      outputParams: [],
    });
  });

  it('seeds omnichannel.message_received with a null (all-channels) channelId', () => {
    const node = createNode('omnichannel.message_received', { x: 0, y: 0 });
    expect(node.kind).toBe('trigger');
    expect(node.config.channelId).toBeNull();
  });

  it('seeds omnichannel.get_contact + omnichannel.send_message', () => {
    const getContact = createNode('omnichannel.get_contact', { x: 0, y: 0 });
    expect(getContact.kind).toBe('action');
    expect(getContact.config).toEqual({ contactId: '' });

    const sendMessage = createNode('omnichannel.send_message', { x: 0, y: 0 });
    expect(sendMessage.kind).toBe('action');
    expect(sendMessage.config).toEqual({ contactId: '', message: '' });
  });

  it('rejects a nonempty AI output-parameter list with a blank key', () => {
    expect(validateDefinition(aiDoc([{ key: '   ', type: 'string', required: true }]))).toContainEqual({
      level: 'error',
      message: 'AI Agent: "Output parameters" contains a parameter without a key.',
      nodeId: 'ai_1',
    });
  });

  it.each([
    {
      name: 'duplicate keys',
      params: [
        { key: 'intent', type: 'string' },
        { key: 'intent', type: 'number' },
      ],
      message: 'contains duplicate key "intent".',
    },
    {
      name: 'invalid syntax',
      params: [{ key: 'intent-value', type: 'string' }],
      message:
        'contains an invalid key "intent-value". Use letters, numbers, and underscores; start with a letter or underscore.',
    },
    {
      name: 'surrounding whitespace',
      params: [{ key: ' intent', type: 'string' }],
      message: 'contains a key with surrounding whitespace.',
    },
    {
      name: 'invalid type',
      params: [{ key: 'intent', type: 'object' }],
      message: 'contains a parameter with an invalid type.',
    },
  ])('rejects $name', ({ params, message }) => {
    const issues = validateDefinition(aiDoc(params));
    expect(issues).toContainEqual({ level: 'error', message: `AI Agent: "Output parameters" ${message}`, nodeId: 'ai_1' });
  });

  it('requires a non-empty list of parameter objects', () => {
    expect(validateDefinition(aiDoc([]))).toContainEqual({
      level: 'error',
      message: 'AI Agent: "Output parameters" must contain at least one parameter.',
      nodeId: 'ai_1',
    });
    expect(validateDefinition(aiDoc({ key: 'intent', type: 'string' }))).toContainEqual({
      level: 'error',
      message: 'AI Agent: "Output parameters" must be a non-empty list of parameter objects.',
      nodeId: 'ai_1',
    });
  });

  it('accepts valid canonical rows and exposes only valid rows downstream', () => {
    const params = [
      { key: 'intent', type: 'string' as const, required: true },
      { key: '_confidence2', type: 'number' as const, required: false },
      { key: 'ready', type: 'boolean' as const },
    ];
    expect(validateDefinition(aiDoc(params))).toEqual([]);
    expect(
      validAiOutputParams([
        ...params,
        { key: '', type: 'string' },
        { key: 'intent', type: 'string' },
        { key: 'bad-key', type: 'string' },
      ]),
    ).toEqual(params);
  });

  it('accepts Enum output values and stateful flags', () => {
    const params = [{ key: 'status', type: 'enum' as const, enumValues: ['ready', 'blocked'], stateful: true }];
    expect(validateDefinition(aiDoc(params))).toEqual([
      expect.objectContaining({ message: expect.stringContaining('require serialized execution') }),
    ]);
    expect(validAiOutputParams(params)).toEqual(params);
  });

  it('requires a valid Correlation key for serialized execution', () => {
    const doc = aiDoc([{ key: 'intent', type: 'string' }]);
    doc.execution = { mode: 'serialized', correlationKey: 'trigger.conversationId' };
    expect(validateDefinition(doc).some((issue) => issue.message.includes('valid Correlation key'))).toBe(true);
    doc.execution.correlationKey = '{{ trigger.conversationId }}';
    expect(validateDefinition(doc)).toEqual([]);
  });
});
