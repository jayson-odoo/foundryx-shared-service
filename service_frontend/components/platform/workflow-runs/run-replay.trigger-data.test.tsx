/**
 * Plan 31 S3 (AC-WFP-38) - the Logs replay inspector shows the trigger
 * node's captured event data ("Trigger data", no config-input blocks) and
 * a regular step's resolved input / output / error as before.
 */
import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { WorkflowRunDetail } from '@/types/workflows';
import { RunReplay } from './run-replay';

// ---- jsdom shims @xyflow/react needs beyond the global ResizeObserver stub
// (mirrors components/platform/status-engine/status-engine.test.tsx). No
// `any` (plan 31 S3 review SF-8) - `unknown` casts satisfy the no-`any` rule
// for jsdom globals TypeScript's lib doesn't declare. ----
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

function run(): WorkflowRunDetail {
  return {
    id: 'run-1',
    status: 'success',
    triggeredBy: 'event',
    isTest: false,
    actorName: 'System',
    startedAt: '2026-09-06T00:00:00Z',
    finishedAt: '2026-09-06T00:00:01Z',
    durationMs: 1000,
    versionNumber: 1,
    correlationKey: null,
    error: null,
    createdAt: '2026-09-06T00:00:00Z',
    pausedNodeId: null,
    triggerPayload: {},
    definition: {
      schemaVersion: 2,
      nodes: [
        {
          id: 'trg_1',
          kind: 'trigger',
          type: 'omnichannel.conversation_opened',
          config: {},
          position: { x: 0, y: 0 },
        },
        {
          id: 'act_1',
          kind: 'action',
          type: 'omnichannel.add_tag',
          config: { contactId: '{{ trigger.contact.id }}', tagId: 'tag-1' },
          position: { x: 0, y: 150 },
        },
      ],
      edges: [{ id: 'e1', source: 'trg_1', target: 'act_1', sourcePort: 'out' }],
    },
    nodes: [
      {
        nodeId: 'trg_1',
        nodeType: 'omnichannel.conversation_opened',
        status: 'success',
        inputJson: null,
        outputJson: {
          triggeredBy: 'event',
          contact: { id: 'cnt-1', name: 'Test Customer', phone: '+60111000111' },
          conversationId: 'cnt-1',
          workspaceId: 'ws-1',
          isReopen: false,
          channelId: 'chn-1',
        },
        error: null,
        startedAt: null,
        finishedAt: null,
      },
      {
        nodeId: 'act_1',
        nodeType: 'omnichannel.add_tag',
        status: 'success',
        inputJson: { config: { tagId: 'tag-1' }, resolved: { contactId: 'cnt-1' } },
        outputJson: { tags: ['VIP'], changed: true },
        error: null,
        startedAt: null,
        finishedAt: null,
      },
    ],
  };
}

describe('RunReplay node inspector - AC-WFP-38', () => {
  it('shows "Trigger data" (the captured event) for the trigger node, with no Input block', async () => {
    render(<RunReplay run={run()} onDebugInEditor={vi.fn()} />);
    fireEvent.click(await screen.findByTestId('workflow-node-trg_1'));

    const inspector = within(await screen.findByTestId('node-inspector'));
    expect(inspector.getByText('Conversation opened')).toBeInTheDocument();
    expect(inspector.getByText('Trigger data')).toBeInTheDocument();
    expect(inspector.queryByText('Input')).not.toBeInTheDocument();
    expect(inspector.queryByText('Resolved input')).not.toBeInTheDocument();
    expect(inspector.getByText(/"phone": "\+60111000111"/)).toBeInTheDocument();
  });

  it('shows Input/Output (not "Trigger data") for a regular step', async () => {
    render(<RunReplay run={run()} onDebugInEditor={vi.fn()} />);
    fireEvent.click(await screen.findByTestId('workflow-node-act_1'));

    const inspector = within(await screen.findByTestId('node-inspector'));
    expect(inspector.getByText('Input')).toBeInTheDocument();
    expect(inspector.getByText('Output')).toBeInTheDocument();
    expect(inspector.queryByText('Trigger data')).not.toBeInTheDocument();
  });
});
