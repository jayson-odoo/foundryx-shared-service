import { describe, expect, it } from 'vitest';
import { redisConfigIssues, validateDefinition } from './workflow-doc';
import type { WorkflowDefinition } from '@/types/workflows';

describe('redisConfigIssues (parity with backend literal_config_issues)', () => {
  it('flags unsupported operation, bad list end, bad ttl, bad amount, reserved key', () => {
    expect(redisConfigIssues({ operation: 'bogus', key: 'k' })).toHaveLength(1);
    expect(
      redisConfigIssues({ operation: 'list_push', key: 'k', value: 'v', end: 'middle' }),
    ).toEqual(['Redis: "List end" must be Left or Right.']);
    expect(
      redisConfigIssues({ operation: 'set', key: 'k', value: 'v', ttlSeconds: '-1' }),
    ).toEqual(['Redis: "TTL seconds" must be a positive whole number.']);
    expect(redisConfigIssues({ operation: 'increment', key: 'k', amount: '1.5' })).toEqual([
      'Redis: "Amount" must be a whole number.',
    ]);
    expect(redisConfigIssues({ operation: 'get', key: 'foundryx:internal' })).toEqual([
      'Redis: that key prefix is reserved.',
    ]);
  });

  it('never rejects merge expressions at publish time', () => {
    expect(
      redisConfigIssues({ operation: 'set', key: 'k', value: 'v', ttlSeconds: '{{ nodes.a.ttl }}' }),
    ).toEqual([]);
    expect(
      redisConfigIssues({ operation: 'list_pop', key: '{{ trigger.contact.id }}', end: 'left' }),
    ).toEqual([]);
  });

  it('surfaces Redis issues through validateDefinition on the node', () => {
    const doc: WorkflowDefinition = {
      schemaVersion: 2,
      nodes: [
        { id: 'trigger', kind: 'trigger', type: 'manual', config: {}, position: { x: 0, y: 0 } },
        {
          id: 'r',
          kind: 'action',
          type: 'redis.command',
          config: { operation: 'list_push', key: 'k', value: 'v', end: 'middle' },
          position: { x: 0, y: 100 },
        },
      ],
      edges: [{ id: 'e1', source: 'trigger', target: 'r' }],
    };
    const issues = validateDefinition(doc);
    expect(issues.some((i) => i.nodeId === 'r' && i.message.includes('List end'))).toBe(true);
  });
});
