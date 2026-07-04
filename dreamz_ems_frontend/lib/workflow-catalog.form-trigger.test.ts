import { describe, expect, it } from 'vitest';
import { catalogEntry, isTriggerType } from './workflow-catalog';
import { createNode } from './workflow-doc';

describe('form.submitted trigger (sprint-3/02)', () => {
  it('is a registered trigger with a searchable form picker', () => {
    const entry = catalogEntry('form.submitted');
    expect(entry?.kind).toBe('trigger');
    expect(isTriggerType('form.submitted')).toBe(true);
    expect(entry?.fields[0]).toMatchObject({ key: 'formId', type: 'form', required: true });
  });

  it('declares the static run-meta outputs (answers are dynamic)', () => {
    const keys = (catalogEntry('form.submitted')?.outputs ?? []).map((o) => o.key);
    expect(keys).toContain('trigger.formId');
    expect(keys).toContain('trigger.submissionId');
  });

  it('a freshly-dropped node defaults to an empty formId', () => {
    const node = createNode('form.submitted', { x: 0, y: 0 });
    expect(node.kind).toBe('trigger');
    expect(node.config.formId).toBe('');
  });
});
