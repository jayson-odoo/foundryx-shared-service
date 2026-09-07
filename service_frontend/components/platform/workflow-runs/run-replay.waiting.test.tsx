/**
 * Plan 31 S6 (AC-WFP-65) - a run parked at an Ask a question node shows as
 * Waiting with a distinct badge, both on the run header and on the parked
 * node's own inspector badge (the node's trace row is `success` - see
 * `RunReplay`'s comment - so this pins that it never reads as a phantom
 * success/failure).
 */
import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { WorkflowRunDetail } from '@/types/workflows';
import { RunReplay } from './run-replay';

class DOMMatrixReadOnlyStub {
  m22 = 1;
}
const globalWithDOMMatrix = globalThis as unknown as {
  DOMMatrixReadOnly?: typeof DOMMatrixReadOnlyStub;
};
globalWithDOMMatrix.DOMMatrixReadOnly ??= DOMMatrixReadOnlyStub;
Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
  configurable: true,
  get() {
    return 600;
  },
});
Object.defineProperty(HTMLElement.prototype, 'offsetWidth', {
  configurable: true,
  get() {
    return 800;
  },
});
const svgProtoWithBBox = SVGElement.prototype as unknown as {
  getBBox: () => { x: number; y: number; width: number; height: number };
};
svgProtoWithBBox.getBBox = () => ({ x: 0, y: 0, width: 0, height: 0 });

function waitingRun(): WorkflowRunDetail {
  return {
    id: 'run-1',
    status: 'waiting',
    triggeredBy: 'event',
    isTest: false,
    actorName: 'System',
    startedAt: '2026-09-06T00:00:00Z',
    finishedAt: null,
    durationMs: null,
    versionNumber: 1,
    correlationKey: '{{ trigger.contact.id }}',
    error: null,
    createdAt: '2026-09-06T00:00:00Z',
    pausedNodeId: 'ask_1',
    triggerPayload: {},
    definition: {
      schemaVersion: 2,
      nodes: [
        {
          id: 'trg_1',
          kind: 'trigger',
          type: 'omnichannel.message_received',
          config: {},
          position: { x: 0, y: 0 },
        },
        {
          id: 'ask_1',
          kind: 'action',
          type: 'omnichannel.ask_question',
          config: { contactId: '{{ trigger.contact.id }}', answerType: 'choice' },
          position: { x: 0, y: 150 },
        },
        {
          id: 'act_1',
          kind: 'action',
          type: 'omnichannel.add_tag',
          config: { contactId: '{{ trigger.contact.id }}', tagId: 'tag-1' },
          position: { x: 0, y: 300 },
        },
      ],
      edges: [
        { id: 'e1', source: 'trg_1', target: 'ask_1', sourcePort: 'out' },
        { id: 'e2', source: 'ask_1', target: 'act_1', sourcePort: 'answer' },
      ],
    },
    nodes: [
      {
        nodeId: 'trg_1',
        nodeType: 'omnichannel.message_received',
        status: 'success',
        inputJson: null,
        outputJson: { message: { text: 'hi' } },
        error: null,
        startedAt: null,
        finishedAt: null,
      },
      {
        nodeId: 'ask_1',
        nodeType: 'omnichannel.ask_question',
        // The backend records the parked node's own trace row as `success`
        // (D-A5-6, executor.py `_walk`) - the frontend re-labels it.
        status: 'success',
        inputJson: { resolved: { contactId: 'cnt-1' } },
        outputJson: { parked: true },
        error: null,
        startedAt: null,
        finishedAt: null,
      },
      // act_1 has NO trace row yet - it is downstream of the parked node and
      // has not run (AC-WFP-41: downstream nodes are not marked skipped).
    ],
  };
}

describe('RunReplay - waiting run (plan 31 S6, AC-WFP-65)', () => {
  it('shows the run header as Waiting, not Success/Failed', () => {
    render(<RunReplay run={waitingRun()} onDebugInEditor={vi.fn()} />);
    expect(screen.getByText('Waiting')).toBeInTheDocument();
    expect(screen.queryByText('Success')).not.toBeInTheDocument();
    expect(screen.queryByText('Failed')).not.toBeInTheDocument();
  });

  it('the parked node inspector shows waiting, never a phantom success', async () => {
    render(<RunReplay run={waitingRun()} onDebugInEditor={vi.fn()} />);
    fireEvent.click(await screen.findByTestId('workflow-node-ask_1'));

    const inspector = within(await screen.findByTestId('node-inspector'));
    expect(inspector.getByText('waiting')).toBeInTheDocument();
    expect(inspector.queryByText('success')).not.toBeInTheDocument();
    expect(inspector.queryByText('failed')).not.toBeInTheDocument();
  });

  it('a node with no trace row (downstream of the park) is not marked failed', async () => {
    render(<RunReplay run={waitingRun()} onDebugInEditor={vi.fn()} />);
    fireEvent.click(await screen.findByTestId('workflow-node-act_1'));

    const inspector = within(await screen.findByTestId('node-inspector'));
    expect(inspector.queryByText('failed')).not.toBeInTheDocument();
  });
});
