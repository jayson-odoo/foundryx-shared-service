/**
 * NodeConfigDrawer - the 4 new field paths from plan sprint-4/17 (AC-OA-20):
 * omnichannelChannel picker, aiAgent picker, output-parameter editor, and the
 * omnichannel actions' mergeable text/textarea fields.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { NodeConfigDrawer } from './node-config-drawer';
import { createNode } from '@/lib/workflow-doc';
import type { WorkflowDefinition, WorkflowMetadata } from '@/types/workflows';

function docWith(nodeType: string): { doc: WorkflowDefinition; nodeId: string } {
  const node = { ...createNode(nodeType, { x: 0, y: 0 }), id: 'n1' };
  return { doc: { schemaVersion: 1, nodes: [node], edges: [] }, nodeId: node.id };
}

const BASE_METADATA: WorkflowMetadata = {
  entities: [],
  omnichannelChannels: [
    { id: 'chn-1', name: 'Support line' },
    { id: 'chn-2', name: 'Sales line' },
  ],
  aiAgents: [
    { id: 'agent-1', name: 'Classifier', model: 'gpt-4o' },
    { id: 'agent-2', name: 'Summarizer', model: 'gpt-4o-mini' },
  ],
};

describe('NodeConfigDrawer - omnichannel + AI Agent field paths', () => {
  it('renders the channel picker for omnichannel.message_received, "All channels" first', async () => {
    const user = userEvent.setup();
    const { doc, nodeId } = docWith('omnichannel.message_received');
    const node = doc.nodes[0];
    render(
      <NodeConfigDrawer
        node={node}
        doc={doc}
        editing
        templateOptions={[]}
        metadata={BASE_METADATA}
        onConfigChange={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(nodeId).toBe('n1');
    const trigger = screen.getByLabelText('Channel');
    expect(trigger).toHaveTextContent('All channels');
    await user.click(trigger);
    expect(screen.getByText('Support line')).toBeInTheDocument();
    expect(screen.getByText('Sales line')).toBeInTheDocument();
  });

  it('selecting "All channels" writes null, a real channel writes its id', async () => {
    const user = userEvent.setup();
    const { doc } = docWith('omnichannel.message_received');
    const node = doc.nodes[0];
    const onConfigChange = vi.fn();
    render(
      <NodeConfigDrawer
        node={node}
        doc={doc}
        editing
        templateOptions={[]}
        metadata={BASE_METADATA}
        onConfigChange={onConfigChange}
        onDelete={vi.fn()}
      />,
    );
    await user.click(screen.getByLabelText('Channel'));
    await user.click(screen.getByText('Support line'));
    expect(onConfigChange).toHaveBeenCalledWith(node.id, { channelId: 'chn-1' });
  });

  it('renders the AI agent picker + the output-parameter editor for ai_agent.run', async () => {
    const user = userEvent.setup();
    const { doc } = docWith('ai_agent.run');
    const node = doc.nodes[0];
    render(
      <NodeConfigDrawer
        node={node}
        doc={doc}
        editing
        templateOptions={[]}
        metadata={BASE_METADATA}
        onConfigChange={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    const agentPicker = screen.getByLabelText('Agent');
    await user.click(agentPicker);
    expect(screen.getByText('Classifier · gpt-4o')).toBeInTheDocument();
    expect(screen.getByText('Summarizer · gpt-4o-mini')).toBeInTheDocument();

    expect(screen.getByTestId('output-params-editor')).toBeInTheDocument();
    expect(screen.getByTestId('add-output-param')).toBeInTheDocument();
  });

  it('adding an output param on the drawer patches config.outputParams', async () => {
    const user = userEvent.setup();
    const { doc } = docWith('ai_agent.run');
    const node = doc.nodes[0];
    const onConfigChange = vi.fn();
    render(
      <NodeConfigDrawer
        node={node}
        doc={doc}
        editing
        templateOptions={[]}
        metadata={BASE_METADATA}
        onConfigChange={onConfigChange}
        onDelete={vi.fn()}
      />,
    );
    await user.click(screen.getByTestId('add-output-param'));
    expect(onConfigChange).toHaveBeenCalledWith(node.id, {
      outputParams: [{ key: '', type: 'string', required: true }],
    });
  });

  it('renders mergeable text/textarea fields on the omnichannel actions', () => {
    const { doc } = docWith('omnichannel.send_message');
    const node = doc.nodes[0];
    render(
      <NodeConfigDrawer
        node={node}
        doc={doc}
        editing
        templateOptions={[]}
        metadata={BASE_METADATA}
        onConfigChange={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    // Both `contactId` and `message` are mergeable - rendered by the
    // DynamicContentField (an <input>/<textarea> with the field's aria-label),
    // not the plain `Input` (which would carry a data-testid).
    expect(screen.getByLabelText('Contact')).toBeInTheDocument();
    expect(screen.queryByTestId('field-contactId')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Message')).toBeInTheDocument();
    expect(screen.queryByTestId('field-message')).not.toBeInTheDocument();
  });
});
