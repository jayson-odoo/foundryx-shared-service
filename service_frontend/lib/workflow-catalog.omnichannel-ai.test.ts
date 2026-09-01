import { describe, expect, it } from 'vitest';
import { ACTION_CATALOG, catalogEntry, isTriggerType, TRIGGER_CATALOG } from './workflow-catalog';

describe('omnichannel + AI Agent catalog entries (plan sprint-4/17)', () => {
  it('registers the incoming-message trigger, module-tagged', () => {
    const entry = TRIGGER_CATALOG.find((e) => e.type === 'omnichannel.message_received');
    expect(entry).toBeDefined();
    expect(entry?.kind).toBe('trigger');
    expect(entry?.module).toBe('omnichannel');
    expect(isTriggerType('omnichannel.message_received')).toBe(true);
    expect(catalogEntry('omnichannel.message_received')).toBe(entry);
  });

  it('registers the two omnichannel actions, both module-tagged', () => {
    const getContact = ACTION_CATALOG.find((e) => e.type === 'omnichannel.get_contact');
    const sendMessage = ACTION_CATALOG.find((e) => e.type === 'omnichannel.send_message');
    expect(getContact).toBeDefined();
    expect(getContact?.kind).toBe('action');
    expect(getContact?.module).toBe('omnichannel');
    expect(sendMessage).toBeDefined();
    expect(sendMessage?.kind).toBe('action');
    expect(sendMessage?.module).toBe('omnichannel');
    expect(getContact?.outputs?.map((output) => output.key)).toEqual([
      'id',
      'name',
      'phone',
      'email',
      'workspaceId',
      'statusId',
      'status',
    ]);
    expect(catalogEntry('omnichannel.get_contact')).toBe(getContact);
    expect(catalogEntry('omnichannel.send_message')).toBe(sendMessage);
  });

  it('registers ai_agent.run as a core (unmodule-tagged) action', () => {
    const entry = ACTION_CATALOG.find((e) => e.type === 'ai_agent.run');
    expect(entry).toBeDefined();
    expect(entry?.kind).toBe('action');
    expect(entry?.module).toBeUndefined();
    expect(catalogEntry('ai_agent.run')).toBe(entry);
  });

  it('the AI Agent action declares its config fields and no static outputs', () => {
    const entry = catalogEntry('ai_agent.run');
    const keys = (entry?.fields ?? []).map((f) => f.key);
    expect(keys).toEqual(['agentId', 'instructions', 'inputText', 'outputParams', 'clarificationOutputKey']);
    const outputSchemaField = entry?.fields.find((f) => f.key === 'outputParams');
    expect(outputSchemaField?.type).toBe('outputSchema');
    const agentField = entry?.fields.find((f) => f.key === 'agentId');
    expect(agentField?.type).toBe('aiAgent');
    expect(entry?.outputs).toEqual([]);
  });

  it('registers generic state, Redis, and permission-gated Code actions', () => {
    expect(catalogEntry('ai_agent.clear_state')?.fields[0]).toMatchObject({ type: 'agentNode' });
    const redis = catalogEntry('redis.command');
    expect(redis?.fields.find((field) => field.key === 'operation')?.options?.map((option) => option.label)).toEqual([
      'Get', 'Set', 'Delete', 'Increment', 'List Push', 'List Pop', 'List Length',
    ]);
    expect(catalogEntry('code.run')).toMatchObject({ permission: 'workflows.code' });
  });

  it('the incoming-message trigger exposes an omnichannelChannel field', () => {
    const entry = catalogEntry('omnichannel.message_received');
    expect(entry?.fields).toEqual([
      { key: 'channelId', label: 'Channel', type: 'omnichannelChannel' },
    ]);
  });
});
