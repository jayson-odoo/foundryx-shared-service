import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { Workflow } from '@/types/workflows';
import { useWorkflowForm } from './use-workflow-form';

const { workflowService, workflowMetadataService } = vi.hoisted(() => ({
  workflowService: {
    get: vi.fn(),
    listTemplateOptions: vi.fn(),
    getTestOptions: vi.fn(),
    run: vi.fn(),
  },
  workflowMetadataService: { getMetadata: vi.fn() },
}));

vi.mock('@/services/workflow-service', () => ({ workflowService }));
vi.mock('@/services/workflow-metadata-service', () => ({
  workflowMetadataService,
}));
vi.mock('./use-workflow-actions', () => ({ useWorkflowActions: () => [] }));
vi.mock('./workflow-editor-tab', () => ({
  WorkflowEditorTab: ({ onRun }: { onRun: () => void }) => (
    <button type="button" onClick={onRun}>
      Open run
    </button>
  ),
}));

const WORKFLOW: Workflow = {
  id: 'workflow-1',
  name: 'Classify and reply',
  description: '',
  isActive: true,
  isTrashed: false,
  triggerType: 'omnichannel.message_received',
  triggerLabel: 'Incoming omnichannel message',
  currentVersionNumber: 1,
  hasUnpublishedChanges: false,
  lastRunAt: null,
  lastRunStatus: null,
  updatedAt: '2026-08-26T00:00:00Z',
  draftDefinition: {
    schemaVersion: 1,
    nodes: [
      {
        id: 'trigger-1',
        kind: 'trigger',
        type: 'omnichannel.message_received',
        config: { channelId: 'chn-demo' },
        position: { x: 0, y: 0 },
      },
    ],
    edges: [],
  },
  currentVersionId: 'version-1',
  currentVersion: null,
  createdByName: 'Demo',
  createdAt: '2026-08-26T00:00:00Z',
};

function Harness() {
  const { config, isLoading } = useWorkflowForm('workflow-1', false, true);
  if (isLoading || !config) return <span>Loading</span>;
  const editor = config.tabs.find((tab) => tab.id === 'editor');
  return <>{editor?.render({ editing: false })}</>;
}

describe('useWorkflowForm test-trigger routing', () => {
  it('opens test data for an omnichannel trigger instead of immediately running empty input', async () => {
    const user = userEvent.setup();
    workflowService.get.mockResolvedValue(WORKFLOW);
    workflowService.listTemplateOptions.mockResolvedValue([]);
    workflowMetadataService.getMetadata.mockResolvedValue({
      entities: [],
    });
    workflowService.getTestOptions.mockResolvedValue({
      omnichannelTestSources: [
        {
          channelId: 'chn-demo',
          channelName: 'Demo sandbox',
          contactId: 'cnt-001',
          contactName: 'Alice',
          contactPhone: '+6012',
        },
      ],
    });

    render(<Harness />);
    await user.click(await screen.findByRole('button', { name: 'Open run' }));

    await waitFor(() =>
      expect(
        screen.getByRole('heading', { name: 'Test workflow' }),
      ).toBeInTheDocument(),
    );
    expect(workflowService.getTestOptions).toHaveBeenCalledWith('workflow-1');
    expect(workflowService.run).not.toHaveBeenCalled();
  });
});
