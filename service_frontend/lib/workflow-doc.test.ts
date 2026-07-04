import { describe, expect, it } from 'vitest';
import {
  addEdge,
  addNode,
  createBlankDefinition,
  createNode,
  hasTrigger,
  nodeDisplayName,
  removeNode,
  replaceNodeType,
  topoOrder,
  uniqueNodeName,
  updateNodeConfig,
  validateDefinition,
  wouldCreateCycle,
} from './workflow-doc';
import type { WorkflowDefinition } from '@/types/workflows';

/** A complete, publishable manual→email graph (required fields filled). */
function manualEmailDoc(): WorkflowDefinition {
  let doc = createBlankDefinition();
  const trigger = { ...createNode('manual', { x: 0, y: 0 }), id: 'trg' };
  const action = {
    ...createNode('email.send', { x: 0, y: 100 }),
    id: 'act',
    config: { templateId: 'tpl-welcome', to: '{{ trigger.input.email }}' },
  };
  doc = addNode(doc, trigger);
  doc = addNode(doc, action);
  doc = addEdge(doc, { source: 'trg', target: 'act', sourcePort: 'out' });
  return doc;
}

describe('createNode', () => {
  it('infers kind + default config from the catalog', () => {
    const trigger = createNode('manual', { x: 0, y: 0 });
    expect(trigger.kind).toBe('trigger');
    expect(trigger.config.inputs).toEqual([]);
    expect(createNode('email.send', { x: 0, y: 0 }).kind).toBe('action');
  });

  it('infers slice-09 node kinds + seeds their config', () => {
    const ifNode = createNode('if', { x: 0, y: 0 });
    expect(ifNode.kind).toBe('if');
    expect(ifNode.config.conditions).toBeNull();
    expect(ifNode.id.startsWith('if_')).toBe(true);

    const created = createNode('entity.created', { x: 0, y: 0 });
    expect(created.kind).toBe('trigger');
    expect(created.config.entityType).toBe('');

    const cron = createNode('schedule.cron', { x: 0, y: 0 });
    expect(cron.config.cron).toBe('0 9 * * *');

    const update = createNode('entity.update', { x: 0, y: 0 });
    expect(update.kind).toBe('action');
    expect(update.config.assignments).toEqual([]);

    const fieldChanged = createNode('entity.field_changed', { x: 0, y: 0 });
    expect(fieldChanged.config).toMatchObject({ entityType: '', field: '' });
  });
});

describe('node names (n8n disambiguation)', () => {
  it('falls back to the catalog label when unnamed, else the set name', () => {
    const node = createNode('email.send', { x: 0, y: 0 });
    expect(nodeDisplayName(node, 'Send email')).toBe('Send email');
    node.config.name = 'Notify customer';
    expect(nodeDisplayName(node, 'Send email')).toBe('Notify customer');
  });

  it('dedupes a default name against existing nodes', () => {
    let doc = createBlankDefinition();
    doc = addNode(doc, { ...createNode('email.send', { x: 0, y: 0 }), id: 'a', config: { name: 'Send email' } });
    expect(uniqueNodeName(doc, 'Send email')).toBe('Send email 2');
    doc = addNode(doc, { ...createNode('email.send', { x: 0, y: 0 }), id: 'b', config: { name: 'Send email 2' } });
    expect(uniqueNodeName(doc, 'Send email')).toBe('Send email 3');
    expect(uniqueNodeName(doc, 'Store a file')).toBe('Store a file');
  });
});

describe('replaceNodeType', () => {
  it('swaps the catalog type in place, keeping id + name, resetting config', () => {
    let doc = createBlankDefinition();
    doc = addNode(doc, {
      ...createNode('entity.created', { x: 0, y: 0 }),
      id: 'trg',
      config: { entityType: 'user', name: 'My trigger' },
    });
    doc = replaceNodeType(doc, 'trg', 'schedule.cron');
    const n = doc.nodes.find((x) => x.id === 'trg')!;
    expect(n.type).toBe('schedule.cron');
    expect(n.kind).toBe('trigger');
    expect(n.config.name).toBe('My trigger'); // name preserved
    expect(n.config.cron).toBe('0 9 * * *'); // reset to new defaults
    expect(n.config.entityType).toBeUndefined();
  });
});

describe('hasTrigger', () => {
  it('detects the single trigger', () => {
    expect(hasTrigger(createBlankDefinition())).toBe(false);
    expect(hasTrigger(manualEmailDoc())).toBe(true);
  });
});

describe('addEdge', () => {
  it('replaces an existing edge on the same source port (n8n reconnect)', () => {
    let doc = manualEmailDoc();
    const other = { ...createNode('email.send', { x: 0, y: 200 }), id: 'act2' };
    doc = addNode(doc, other);
    doc = addEdge(doc, { source: 'trg', target: 'act2', sourcePort: 'out' });
    const fromTrigger = doc.edges.filter((e) => e.source === 'trg');
    expect(fromTrigger).toHaveLength(1);
    expect(fromTrigger[0].target).toBe('act2');
  });
});

describe('removeNode', () => {
  it('drops the node and every edge touching it', () => {
    const doc = removeNode(manualEmailDoc(), 'act');
    expect(doc.nodes.map((n) => n.id)).toEqual(['trg']);
    expect(doc.edges).toHaveLength(0);
  });
});

describe('updateNodeConfig', () => {
  it('merges the config patch immutably', () => {
    const doc = updateNodeConfig(manualEmailDoc(), 'act', { cc: 'x@y.com' });
    const act = doc.nodes.find((n) => n.id === 'act');
    expect(act?.config.cc).toBe('x@y.com');
    expect(act?.config.templateId).toBe('tpl-welcome'); // existing keys preserved
  });
});

describe('wouldCreateCycle', () => {
  it('flags self-loops and back-edges', () => {
    const doc = manualEmailDoc();
    expect(wouldCreateCycle(doc, 'trg', 'trg')).toBe(true);
    // act -> trg would close a loop (trg -> act already exists).
    expect(wouldCreateCycle(doc, 'act', 'trg')).toBe(true);
    // trg -> act is forward, no cycle.
    expect(wouldCreateCycle(createBlankDefinition(), 'a', 'b')).toBe(false);
  });
});

describe('topoOrder', () => {
  it('orders from the trigger downstream', () => {
    const ordered = topoOrder(manualEmailDoc()).map((n) => n.id);
    expect(ordered).toEqual(['trg', 'act']);
  });
});

describe('validateDefinition', () => {
  it('passes a valid manual→email graph', () => {
    expect(validateDefinition(manualEmailDoc()).filter((i) => i.level === 'error')).toHaveLength(0);
  });

  it('requires a trigger', () => {
    const issues = validateDefinition(createBlankDefinition());
    expect(issues.some((i) => i.message.includes('Add a trigger'))).toBe(true);
  });

  it('blocks orphan nodes', () => {
    let doc = manualEmailDoc();
    doc = addNode(doc, { ...createNode('email.send', { x: 0, y: 300 }), id: 'orphan' });
    const issues = validateDefinition(doc);
    expect(issues.some((i) => i.nodeId === 'orphan' && i.level === 'error')).toBe(true);
  });

  it('flags missing required config (email recipient + template)', () => {
    let doc = createBlankDefinition();
    doc = addNode(doc, { ...createNode('manual', { x: 0, y: 0 }), id: 'trg' });
    doc = addNode(doc, { ...createNode('email.send', { x: 0, y: 100 }), id: 'act' });
    doc = addEdge(doc, { source: 'trg', target: 'act', sourcePort: 'out' });
    const issues = validateDefinition(doc); // act has no `to` / `templateId`
    expect(issues.some((i) => i.message.includes('To'))).toBe(true);
    expect(issues.some((i) => i.message.includes('Template'))).toBe(true);
  });

  it('rejects duplicate node names', () => {
    let doc = createBlankDefinition();
    doc = addNode(doc, { ...createNode('manual', { x: 0, y: 0 }), id: 'trg', config: { inputs: [], name: 'Dup' } });
    doc = addNode(doc, {
      ...createNode('email.send', { x: 0, y: 100 }),
      id: 'act',
      config: { templateId: 't', to: 'a@b.com', name: 'Dup' },
    });
    doc = addEdge(doc, { source: 'trg', target: 'act', sourcePort: 'out' });
    expect(validateDefinition(doc).some((i) => i.message.includes('must be unique'))).toBe(true);
  });

  it('rejects more than one trigger', () => {
    let doc = manualEmailDoc();
    doc = addNode(doc, { ...createNode('manual', { x: 200, y: 0 }), id: 'trg2' });
    expect(validateDefinition(doc).some((i) => i.message.includes('only one trigger'))).toBe(true);
  });

  it('requires the entity on an entity trigger + field on field_changed', () => {
    let doc = createBlankDefinition();
    doc = addNode(doc, { ...createNode('entity.field_changed', { x: 0, y: 0 }), id: 'trg' });
    doc = addNode(doc, {
      ...createNode('email.send', { x: 0, y: 100 }),
      id: 'act',
      config: { templateId: 'tpl', to: 'x@y.com' },
    });
    doc = addEdge(doc, { source: 'trg', target: 'act', sourcePort: 'out' });
    const issues = validateDefinition(doc);
    expect(issues.some((i) => i.message.includes('Entity'))).toBe(true);
    expect(issues.some((i) => i.message.includes('Field'))).toBe(true);
  });

  it('accepts an IF node reached and branching via true/false ports', () => {
    let doc = createBlankDefinition();
    doc = addNode(doc, { ...createNode('entity.created', { x: 0, y: 0 }), id: 'trg', config: { entityType: 'user' } });
    doc = addNode(doc, { ...createNode('if', { x: 0, y: 100 }), id: 'cond' });
    doc = addNode(doc, { ...createNode('email.send', { x: 0, y: 200 }), id: 'yes', config: { templateId: 't', to: 'a@b.com', name: 'Yes mail' } });
    doc = addNode(doc, { ...createNode('email.send', { x: 200, y: 200 }), id: 'no', config: { templateId: 't', to: 'c@d.com', name: 'No mail' } });
    doc = addEdge(doc, { source: 'trg', target: 'cond', sourcePort: 'out' });
    doc = addEdge(doc, { source: 'cond', target: 'yes', sourcePort: 'true' });
    doc = addEdge(doc, { source: 'cond', target: 'no', sourcePort: 'false' });
    expect(validateDefinition(doc).filter((i) => i.level === 'error')).toHaveLength(0);
  });
});
