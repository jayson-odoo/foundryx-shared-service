/**
 * Generic multi-port node rendering (plan 31 D-A5-14, AC-WFP-05) - a branching
 * action (Ask a question, Business hours) renders one labelled source handle
 * per declared `ports` entry exactly like the IF node's true/false handles; a
 * plain action keeps the single `out` handle.
 */
import { ReactFlowProvider } from '@xyflow/react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { WorkflowFlowNode } from './workflow-node';
import { catalogEntry } from '@/lib/workflow-catalog';
import { createNode } from '@/lib/workflow-doc';
import type { WorkflowNodeData } from './workflow-node';

function renderNode(type: string) {
  const node = createNode(type, { x: 0, y: 0 });
  const data: WorkflowNodeData = { node, catalog: catalogEntry(type) };
  return render(
    <ReactFlowProvider>
      <WorkflowFlowNode
        id={node.id}
        data={data}
        selected={false}
        type="workflow"
        dragging={false}
        zIndex={0}
        isConnectable
        positionAbsoluteX={0}
        positionAbsoluteY={0}
      />
    </ReactFlowProvider>,
  );
}

describe('WorkflowFlowNode - generic ports', () => {
  it('renders two labelled source handles for Ask a question, like the IF node', () => {
    renderNode('omnichannel.ask_question');
    expect(screen.getByTestId('source-handle-answer')).toBeInTheDocument();
    expect(screen.getByTestId('source-handle-timeout')).toBeInTheDocument();
    expect(screen.queryByTestId('source-handle')).not.toBeInTheDocument();
  });

  it('renders inside/outside handles for Business hours', () => {
    renderNode('omnichannel.business_hours');
    expect(screen.getByTestId('source-handle-inside')).toBeInTheDocument();
    expect(screen.getByTestId('source-handle-outside')).toBeInTheDocument();
  });

  it('keeps the single `out` handle for a non-branching action', () => {
    renderNode('omnichannel.wait');
    expect(screen.getByTestId('source-handle')).toBeInTheDocument();
    expect(screen.queryByTestId('source-handle-answer')).not.toBeInTheDocument();
  });

  it('still renders the IF node true/false handles unchanged', () => {
    renderNode('if');
    expect(screen.getByTestId('source-handle-true')).toBeInTheDocument();
    expect(screen.getByTestId('source-handle-false')).toBeInTheDocument();
  });
});
