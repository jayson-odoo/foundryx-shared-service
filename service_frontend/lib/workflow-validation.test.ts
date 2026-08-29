import { describe, expect, it } from 'vitest';
import type { Workflow, WorkflowDefinition } from '@/types/workflows';
import { createNode } from './workflow-doc';
import { workflowPublishIssue } from './workflow-validation';

const codeNode = (id = 'code-1') => ({
  ...createNode('code.run', { x: 0, y: 100 }),
  id,
  config: {
    language: 'python',
    source: 'result = {}',
    inputs: [],
    outputs: [{ key: 'summary', type: 'string' as const }],
  },
});

function workflow(
  definition: WorkflowDefinition,
  currentVersionId: string | null,
  definitionBaseline?: WorkflowDefinition,
): Workflow {
  return {
    id: 'wf-test',
    name: 'Test workflow',
    description: '',
    isActive: false,
    isTrashed: false,
    triggerType: 'manual',
    triggerLabel: 'Manual',
    currentVersionNumber: currentVersionId ? 1 : null,
    hasUnpublishedChanges: true,
    lastRunAt: null,
    lastRunStatus: null,
    updatedAt: '',
    draftDefinition: definition,
    currentVersionId,
    currentVersion: currentVersionId
      ? {
          id: currentVersionId,
          versionNumber: 1,
          publishedAt: '',
          publishedByName: '',
          notes: null,
          definition: definitionBaseline,
        }
      : null,
    createdByName: '',
    createdAt: '',
  };
}

const metadata = { entities: [], codeRunnerAvailable: false };
const definition = (node = codeNode()): WorkflowDefinition => ({
  schemaVersion: 2,
  nodes: [{ ...createNode('manual', { x: 0, y: 0 }), id: 'trigger-1' }, node],
  edges: [
    { id: 'edge-1', source: 'trigger-1', target: node.id, sourcePort: 'out' },
  ],
});

describe('workflowPublishIssue', () => {
  it('fails closed when a stored Code baseline is unavailable', () => {
    expect(
      workflowPublishIssue(
        workflow(definition(), 'published-1'),
        metadata,
        true,
      ),
    ).toContain('could not be verified');
  });

  it('allows an unchanged Code definition when the baseline is present', () => {
    const current = definition();
    expect(
      workflowPublishIssue(
        workflow(current, 'published-1', current),
        metadata,
        true,
      ),
    ).toBeNull();
  });

  it('gates Code publication by permission and changed runner health', () => {
    expect(
      workflowPublishIssue(workflow(definition(), null), metadata, false),
    ).toContain('workflows.code');
    const baseline = definition();
    const changed = definition({
      ...codeNode(),
      config: { ...codeNode().config, source: 'result = {"changed": True}' },
    });
    expect(
      workflowPublishIssue(
        workflow(changed, 'published-1', baseline),
        metadata,
        true,
      ),
    ).toContain('changed Code');
  });
});
