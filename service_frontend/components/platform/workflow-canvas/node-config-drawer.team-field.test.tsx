/**
 * NodeConfigDrawer - the `team` NodeField type (plan 28, roadmap A8): a
 * `SearchSelect` over `metadata.teams`, mirroring `omnichannelChannel`/
 * `aiAgent`. No real action registers this field type yet (that lands with
 * `omnichannel.assign_conversation` in S3) - this test injects a synthetic
 * catalog entry so the field-rendering branch is exercised in isolation.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/workflow-catalog', async () => {
  const actual = await vi.importActual<typeof import('@/lib/workflow-catalog')>(
    '@/lib/workflow-catalog',
  );
  return {
    ...actual,
    catalogEntry: (type: string) =>
      type === 'test.team_field'
        ? {
            kind: 'action' as const,
            type: 'test.team_field',
            label: 'Test Team Field',
            description: 'Synthetic entry for the team NodeField test.',
            icon: 'Users',
            category: 'Actions',
            fields: [{ key: 'teamId', label: 'Team', type: 'team' as const, required: true }],
            outputs: [],
          }
        : actual.catalogEntry(type),
  };
});

import { NodeConfigDrawer } from './node-config-drawer';
import type { WorkflowDefinition, WorkflowMetadata, WorkflowNode } from '@/types/workflows';

const METADATA: WorkflowMetadata = {
  entities: [],
  teams: [
    { id: 'team-1', name: 'Sales' },
    { id: 'team-2', name: 'Support' },
  ],
};

function makeNode(): WorkflowNode {
  return { id: 'n1', kind: 'action', type: 'test.team_field', config: {}, position: { x: 0, y: 0 } };
}

describe('NodeConfigDrawer - team NodeField (plan 28)', () => {
  it('renders a SearchSelect over metadata.teams', async () => {
    const user = userEvent.setup();
    const node = makeNode();
    const doc: WorkflowDefinition = { schemaVersion: 2, nodes: [node], edges: [] };
    render(
      <NodeConfigDrawer
        node={node}
        doc={doc}
        editing
        templateOptions={[]}
        metadata={METADATA}
        onConfigChange={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    const trigger = screen.getByLabelText('Team');
    expect(trigger).toHaveTextContent('Choose a team…');
    await user.click(trigger);
    expect(screen.getByText('Sales')).toBeInTheDocument();
    expect(screen.getByText('Support')).toBeInTheDocument();
  });

  it('writes the selected team id onto the field key', async () => {
    const user = userEvent.setup();
    const node = makeNode();
    const doc: WorkflowDefinition = { schemaVersion: 2, nodes: [node], edges: [] };
    const onConfigChange = vi.fn();
    render(
      <NodeConfigDrawer
        node={node}
        doc={doc}
        editing
        templateOptions={[]}
        metadata={METADATA}
        onConfigChange={onConfigChange}
        onDelete={vi.fn()}
      />,
    );

    await user.click(screen.getByLabelText('Team'));
    await user.click(screen.getByText('Support'));
    expect(onConfigChange).toHaveBeenCalledWith('n1', { teamId: 'team-2' });
  });

  it('an empty metadata.teams renders an empty (never a foreign-tenant) picker', async () => {
    const user = userEvent.setup();
    const node = makeNode();
    const doc: WorkflowDefinition = { schemaVersion: 2, nodes: [node], edges: [] };
    render(
      <NodeConfigDrawer
        node={node}
        doc={doc}
        editing
        templateOptions={[]}
        metadata={{ entities: [] }}
        onConfigChange={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    await user.click(screen.getByLabelText('Team'));
    expect(screen.getByText('No matches.')).toBeInTheDocument();
  });
});
