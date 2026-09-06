/**
 * Plan 31 (omnichannel workflow parity) drawer coverage - AC-WFP-02/03/04.
 * Workspace-scoped pickers are disabled + empty until a workspace is chosen,
 * boolean flags render as a labelled checkbox (no bare `<Select>`), and
 * switching a controlling field clears its hidden dependents from config.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { NodeConfigDrawer } from './node-config-drawer';
import { createNode } from '@/lib/workflow-doc';
import type { WorkflowDefinition, WorkflowMetadata } from '@/types/workflows';

function docWith(nodeType: string, config?: Record<string, unknown>) {
  const node = { ...createNode(nodeType, { x: 0, y: 0 }), id: 'n1' };
  if (config) node.config = { ...node.config, ...config };
  return { doc: { schemaVersion: 2, nodes: [node], edges: [] } as WorkflowDefinition, node };
}

const METADATA: WorkflowMetadata = {
  entities: [],
  omnichannelWorkspaces: [
    {
      id: 'ws-1',
      name: 'General',
      contactTags: [{ id: 'tag-1', name: 'VIP' }],
      contactFields: [{ key: 'company', label: 'Company', type: 'string' }],
      lifecycleStages: [{ id: 'stage-1', name: 'New' }],
      closeReasons: [
        { id: 'reason-1', name: 'Resolved', isActive: true },
        { id: 'reason-2', name: 'Retired', isActive: false },
      ],
      members: [{ id: 'user-1', name: 'Demo Admin' }],
      templates: [
        { id: 'tpl-1', name: 'welcome_message', status: 'APPROVED' },
        { id: 'tpl-2', name: 'pending_template', status: 'PENDING' },
      ],
    },
  ],
  workflows: [{ id: 'wf-1', name: 'Onboarding' }],
};

describe('NodeConfigDrawer - plan 31 workspace-scoped pickers (AC-WFP-03)', () => {
  it('the tag picker is disabled and empty until a workspace is chosen', async () => {
    const { doc, node } = docWith('omnichannel.add_tag');
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
    const tagPicker = screen.getByLabelText('Tag');
    expect(tagPicker).toBeDisabled();
    expect(tagPicker).toHaveTextContent('Choose a workspace first');
  });

  it('choosing a workspace enables the tag picker scoped to that workspace only', async () => {
    const user = userEvent.setup();
    const { doc, node } = docWith('omnichannel.add_tag', { workspaceId: 'ws-1' });
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
    const tagPicker = screen.getByLabelText('Tag');
    expect(tagPicker).not.toBeDisabled();
    await user.click(tagPicker);
    expect(screen.getByText('VIP')).toBeInTheDocument();
  });

  it('changing the workspace clears the already-chosen scoped field', async () => {
    const user = userEvent.setup();
    const onConfigChange = vi.fn();
    const { doc, node } = docWith('omnichannel.add_tag', {
      workspaceId: 'ws-1',
      tagId: 'tag-1',
    });
    render(
      <NodeConfigDrawer
        node={node}
        doc={doc}
        editing
        templateOptions={[]}
        metadata={{
          ...METADATA,
          omnichannelWorkspaces: [
            ...METADATA.omnichannelWorkspaces!,
            { ...METADATA.omnichannelWorkspaces![0], id: 'ws-2', name: 'Sales' },
          ],
        }}
        onConfigChange={onConfigChange}
        onDelete={vi.fn()}
      />,
    );
    await user.click(screen.getByLabelText('Workspace'));
    await user.click(screen.getByText('Sales'));
    expect(onConfigChange).toHaveBeenCalledWith(node.id, {
      workspaceId: 'ws-2',
      tagId: '',
    });
  });

  it('the close reason picker only lists ACTIVE reasons', async () => {
    const user = userEvent.setup();
    const { doc, node } = docWith('omnichannel.close_conversation', { workspaceId: 'ws-1' });
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
    await user.click(screen.getByLabelText('Close reason'));
    expect(screen.getByText('Resolved')).toBeInTheDocument();
    expect(screen.queryByText('Retired')).not.toBeInTheDocument();
  });

  it('the template picker only lists APPROVED templates, tenant-wide', async () => {
    const user = userEvent.setup();
    const { doc, node } = docWith('omnichannel.send_message', { mode: 'template' });
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
    await user.click(screen.getByLabelText('Template'));
    expect(screen.getByText('welcome_message')).toBeInTheDocument();
    expect(screen.queryByText('pending_template')).not.toBeInTheDocument();
  });
});

describe('NodeConfigDrawer - boolean flags render as a checkbox (AC-WFP-02)', () => {
  it('renders "Trigger once per contact" as a labelled checkbox, unchecked by default', () => {
    const { doc, node } = docWith('omnichannel.conversation_opened');
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
    const checkbox = screen.getByLabelText('Trigger once per contact') as HTMLInputElement;
    expect(checkbox.type).toBe('checkbox');
    expect(checkbox.checked).toBe(false);
  });

  it('toggling the checkbox writes true/false to config', async () => {
    const user = userEvent.setup();
    const onConfigChange = vi.fn();
    const { doc, node } = docWith('omnichannel.conversation_opened');
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
    await user.click(screen.getByLabelText('Trigger once per contact'));
    expect(onConfigChange).toHaveBeenCalledWith(node.id, {
      triggerOncePerContact: true,
    });
  });
});

describe('NodeConfigDrawer - show_when clears hidden dependents (AC-WFP-04)', () => {
  it('switching assign mode away from "user" clears the chosen user', async () => {
    const user = userEvent.setup();
    const onConfigChange = vi.fn();
    const { doc, node } = docWith('omnichannel.assign_conversation', {
      workspaceId: 'ws-1',
      mode: 'user',
      userId: 'user-1',
    });
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
    await user.click(screen.getByLabelText('Assign mode'));
    await user.click(screen.getByText('Round robin'));
    expect(onConfigChange).toHaveBeenCalledWith(node.id, {
      mode: 'round_robin',
      userId: '',
    });
  });

  it('the ask_question choices editor only renders for the choice answer type', () => {
    const { doc: textDoc, node: textNode } = docWith('omnichannel.ask_question');
    const { rerender } = render(
      <NodeConfigDrawer
        node={textNode}
        doc={textDoc}
        editing
        templateOptions={[]}
        metadata={METADATA}
        onConfigChange={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(screen.queryByTestId('choice-list-editor')).not.toBeInTheDocument();

    const { doc: choiceDoc, node: choiceNode } = docWith('omnichannel.ask_question', {
      answerType: 'choice',
      choices: ['Yes', 'No'],
    });
    rerender(
      <NodeConfigDrawer
        node={choiceNode}
        doc={choiceDoc}
        editing
        templateOptions={[]}
        metadata={METADATA}
        onConfigChange={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(screen.getByTestId('choice-list-editor')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Yes')).toBeInTheDocument();
    expect(screen.getByDisplayValue('No')).toBeInTheDocument();
  });

  it('the HTTP request body field shows for BOTH json and text body modes', () => {
    const { doc: jsonDoc, node: jsonNode } = docWith('http.request', { bodyMode: 'json' });
    const { rerender } = render(
      <NodeConfigDrawer
        node={jsonNode}
        doc={jsonDoc}
        editing
        templateOptions={[]}
        metadata={METADATA}
        onConfigChange={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(screen.getByLabelText('Body content')).toBeInTheDocument();

    const { doc: noneDoc, node: noneNode } = docWith('http.request', { bodyMode: 'none' });
    rerender(
      <NodeConfigDrawer
        node={noneNode}
        doc={noneDoc}
        editing
        templateOptions={[]}
        metadata={METADATA}
        onConfigChange={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(screen.queryByLabelText('Body content')).not.toBeInTheDocument();
  });

  it('renders the HTTP headers key/value editor', () => {
    const { doc, node } = docWith('http.request');
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
    expect(screen.getByTestId('key-value-editor')).toBeInTheDocument();
  });

  it('renders the workflowRef picker for workflow.trigger', async () => {
    const user = userEvent.setup();
    const { doc, node } = docWith('workflow.trigger');
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
    await user.click(screen.getByLabelText('Workflow'));
    expect(screen.getByText('Onboarding')).toBeInTheDocument();
  });

  it('excludes the workflow being edited from the workflowRef picker (plan 31 S3, AC-WFP-33 parity)', async () => {
    const user = userEvent.setup();
    const { doc, node } = docWith('workflow.trigger');
    const metadataWithSelf: WorkflowMetadata = {
      ...METADATA,
      workflows: [
        { id: 'wf-1', name: 'Onboarding' },
        { id: 'wf-self', name: 'This workflow' },
      ],
    };
    render(
      <NodeConfigDrawer
        node={node}
        doc={doc}
        editing
        templateOptions={[]}
        metadata={metadataWithSelf}
        onConfigChange={vi.fn()}
        onDelete={vi.fn()}
        currentWorkflowId="wf-self"
      />,
    );
    await user.click(screen.getByLabelText('Workflow'));
    expect(screen.getByText('Onboarding')).toBeInTheDocument();
    expect(screen.queryByText('This workflow')).not.toBeInTheDocument();
  });
});
