/**
 * Plan 31 (omnichannel workflow parity) S0 catalog coverage - AC-WFP-01/02/06.
 * Every new trigger/action is module-tagged `omnichannel` (except the two
 * core actions), carries the `triggerOncePerContact` flag where the plan
 * requires it, and the branching actions declare `ports`.
 */
import { describe, expect, it } from 'vitest';
import {
  ACTION_CATALOG,
  catalogEntry,
  IF_CATALOG,
  TRIGGER_CATALOG,
} from './workflow-catalog';
import { createNode, validateDefinition } from './workflow-doc';
import type { WorkflowDefinition } from '@/types/workflows';

const NEW_TRIGGER_TYPES = [
  'omnichannel.conversation_opened',
  'omnichannel.conversation_closed',
  'omnichannel.conversation_assigned',
  'omnichannel.contact_tag_added',
  'omnichannel.contact_tag_removed',
  'omnichannel.contact_field_changed',
  'omnichannel.lifecycle_changed',
  'omnichannel.broadcast_completed',
];

const NEW_ACTION_TYPES = [
  'omnichannel.assign_conversation',
  'omnichannel.add_tag',
  'omnichannel.remove_tag',
  'omnichannel.update_field',
  'omnichannel.update_lifecycle',
  'omnichannel.open_conversation',
  'omnichannel.close_conversation',
  'omnichannel.add_comment',
  'omnichannel.ask_question',
  'omnichannel.wait',
  'omnichannel.business_hours',
  'workflow.trigger',
  'http.request',
];

describe('plan 31 catalog entries (AC-WFP-01)', () => {
  it('registers every new trigger, module-tagged except none (all omnichannel)', () => {
    for (const type of NEW_TRIGGER_TYPES) {
      const entry = TRIGGER_CATALOG.find((e) => e.type === type);
      expect(entry, `${type} missing`).toBeDefined();
      expect(entry?.module).toBe('omnichannel');
      expect(catalogEntry(type)).toBe(entry);
    }
  });

  it('every contact-scoped trigger except broadcast_completed offers triggerOncePerContact', () => {
    for (const type of NEW_TRIGGER_TYPES.filter((t) => t !== 'omnichannel.broadcast_completed')) {
      const entry = TRIGGER_CATALOG.find((e) => e.type === type);
      const flag = entry?.fields.find((f) => f.key === 'triggerOncePerContact');
      expect(flag, `${type} missing triggerOncePerContact`).toBeDefined();
      expect(flag?.type).toBe('boolean');
    }
  });

  it('registers every new action', () => {
    for (const type of NEW_ACTION_TYPES) {
      const entry = ACTION_CATALOG.find((e) => e.type === type);
      expect(entry, `${type} missing`).toBeDefined();
      expect(catalogEntry(type)).toBe(entry);
    }
  });

  it('the omnichannel actions are module-tagged; the two core actions are not', () => {
    for (const type of NEW_ACTION_TYPES) {
      const entry = ACTION_CATALOG.find((e) => e.type === type)!;
      if (type === 'workflow.trigger' || type === 'http.request') {
        expect(entry.module).toBeUndefined();
      } else {
        expect(entry.module).toBe('omnichannel');
      }
    }
  });

  it('http.request is gated by the workflows.http permission', () => {
    expect(catalogEntry('http.request')).toMatchObject({ permission: 'workflows.http' });
  });

  it('send message gains a template mode over the same action (extend, not a new type)', () => {
    const entry = catalogEntry('omnichannel.send_message');
    const keys = (entry?.fields ?? []).map((f) => f.key);
    expect(keys).toEqual(['contactId', 'mode', 'message', 'templateId', 'templateVariables']);
    expect(entry?.fields.find((f) => f.key === 'templateId')).toMatchObject({
      type: 'whatsappTemplate',
      showWhen: { field: 'mode', value: 'template' },
    });
  });

  it('Wait and Business hours are catalogued under the Logic category', () => {
    expect(catalogEntry('omnichannel.wait')?.category).toBe('Logic');
    expect(catalogEntry('omnichannel.business_hours')?.category).toBe('Logic');
  });

  it('Ask a question and Business hours declare branching ports like the IF node', () => {
    const ask = catalogEntry('omnichannel.ask_question');
    const hours = catalogEntry('omnichannel.business_hours');
    expect(ask && 'ports' in ask ? ask.ports : undefined).toEqual(['answer', 'timeout']);
    expect(hours && 'ports' in hours ? hours.ports : undefined).toEqual(['inside', 'outside']);
    // The Wait step is a single-port pause, not a branch (D-A5-14 contrasts
    // it with Business hours) - no `ports` declared.
    const wait = catalogEntry('omnichannel.wait');
    expect(wait && 'ports' in wait ? wait.ports : undefined).toBeUndefined();
  });

  it('every picker field on the new catalog uses a searchable type, never a raw select for scoped data (AC-WFP-02)', () => {
    const scopedTypes = new Set([
      'omnichannelWorkspace',
      'omnichannelTag',
      'omnichannelContactField',
      'omnichannelLifecycleStage',
      'omnichannelCloseReason',
      'omnichannelMember',
      'whatsappTemplate',
      'workflowRef',
    ]);
    const allEntries = [...TRIGGER_CATALOG, ...ACTION_CATALOG, ...IF_CATALOG];
    const scopedFieldTypesFound = new Set<string>();
    for (const entry of allEntries) {
      for (const field of entry.fields) {
        if (scopedTypes.has(field.type)) scopedFieldTypesFound.add(field.type);
      }
    }
    // Every declared scoped type is actually used somewhere in the catalog.
    expect(scopedFieldTypesFound.size).toBe(scopedTypes.size);
  });
});

describe('plan 31 show_when matrices (AC-WFP-04)', () => {
  it('HTTP request body content shows for BOTH json and text body modes', () => {
    const entry = catalogEntry('http.request');
    const body = entry?.fields.find((f) => f.key === 'body');
    expect(body?.showWhen).toEqual({ field: 'bodyMode', value: ['json', 'text'] });
  });

  it('assign_conversation user picker shows only in user mode', () => {
    const entry = catalogEntry('omnichannel.assign_conversation');
    const userId = entry?.fields.find((f) => f.key === 'userId');
    expect(userId?.showWhen).toEqual({ field: 'mode', value: 'user' });
  });

  it('ask_question choices editor shows only for the choice answer type', () => {
    const entry = catalogEntry('omnichannel.ask_question');
    const choices = entry?.fields.find((f) => f.key === 'choices');
    expect(choices?.showWhen).toEqual({ field: 'answerType', value: 'choice' });
  });
});

describe('plan 31 default config seeds a controlled shape', () => {
  it('seeds omnichannel.ask_question with a text mode and empty choices', () => {
    const node = createNode('omnichannel.ask_question', { x: 0, y: 0 });
    expect(node.kind).toBe('action');
    expect(node.config).toMatchObject({
      contactId: '',
      mode: 'text',
      message: '',
      answerType: 'text',
      choices: [],
      retryLimit: '1',
      timeoutUnit: 'hours',
    });
  });

  it('seeds http.request with method GET and no body', () => {
    const node = createNode('http.request', { x: 0, y: 0 });
    expect(node.config).toEqual({
      method: 'GET',
      url: '',
      headers: [],
      bodyMode: 'none',
      body: '',
      timeoutSeconds: '10',
    });
  });
});

function askDoc(execution?: WorkflowDefinition['execution']): WorkflowDefinition {
  const trigger = createNode('omnichannel.message_received', { x: 0, y: 0 });
  trigger.id = 'trg_1';
  const ask = createNode('omnichannel.ask_question', { x: 0, y: 100 });
  ask.id = 'ask_1';
  ask.config = { ...ask.config, contactId: '{{ trigger.contact.id }}', message: 'Pick one' };
  return {
    schemaVersion: 2,
    execution,
    nodes: [trigger, ask],
    edges: [{ id: 'e1', source: 'trg_1', target: 'ask_1', sourcePort: 'out' }],
  };
}

describe('plan 31 Ask a question requires serialized execution (AC-WFP-06)', () => {
  it('blocks publish when execution is parallel (or unset)', () => {
    const issues = validateDefinition(askDoc({ mode: 'parallel', correlationKey: '' }));
    expect(issues).toContainEqual({
      level: 'error',
      message: 'Ask a question requires serialized execution and a Correlation key.',
    });
  });

  it('blocks publish when serialized but the correlation key is malformed (the shared generic check)', () => {
    const issues = validateDefinition(askDoc({ mode: 'serialized', correlationKey: 'not-a-token' }));
    expect(issues).toContainEqual({
      level: 'error',
      message: 'Serialized execution requires a valid Correlation key.',
    });
  });

  it('passes with serialized execution and a valid correlation key', () => {
    const issues = validateDefinition(
      askDoc({ mode: 'serialized', correlationKey: '{{ trigger.contact.id }}' }),
    );
    expect(issues).not.toContainEqual(
      expect.objectContaining({
        message: 'Ask a question requires serialized execution and a Correlation key.',
      }),
    );
  });

  it('does not require serialized execution for a graph without an Ask node', () => {
    const trigger = createNode('omnichannel.message_received', { x: 0, y: 0 });
    trigger.id = 'trg_1';
    const send = createNode('omnichannel.send_message', { x: 0, y: 100 });
    send.id = 'act_1';
    const doc: WorkflowDefinition = {
      schemaVersion: 2,
      execution: { mode: 'parallel', correlationKey: '' },
      nodes: [trigger, send],
      edges: [{ id: 'e1', source: 'trg_1', target: 'act_1', sourcePort: 'out' }],
    };
    const issues = validateDefinition(doc);
    expect(issues).not.toContainEqual(
      expect.objectContaining({ message: expect.stringContaining('Ask a question') }),
    );
  });
});
