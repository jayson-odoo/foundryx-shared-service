import { describe, expect, it } from 'vitest';
import { createNode } from './workflow-doc';

describe('createNode defaultConfig - omnichannel + AI Agent nodes (plan sprint-4/17)', () => {
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
});
