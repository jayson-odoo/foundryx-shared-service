import { beforeEach, describe, expect, it, vi } from 'vitest';
import { realWorkflowService as service } from './workflow-service.real';

const { apiFetch } = vi.hoisted(() => ({ apiFetch: vi.fn() }));

vi.mock('@/lib/api-client', async () => {
  const actual =
    await vi.importActual<typeof import('@/lib/api-client')>(
      '@/lib/api-client',
    );
  return { ...actual, apiFetch };
});

beforeEach(() => apiFetch.mockReset());

describe('realWorkflowService', () => {
  it('loads permission-gated test options for one workflow', async () => {
    apiFetch.mockResolvedValue({ omnichannelTestSources: [] });

    await service.getTestOptions('workflow-1');

    expect(apiFetch).toHaveBeenCalledWith('/workflows/workflow-1/test-options');
  });

  it('posts typed omnichannel test-trigger data unchanged', async () => {
    apiFetch.mockResolvedValue({ id: 'run-1' });
    const request = {
      inputs: {},
      isTest: true,
      testTrigger: {
        type: 'omnichannel.message_received' as const,
        channelId: 'chn-demo',
        contactId: 'cnt-001',
        messageText: 'Test booking message',
      },
    };

    await service.run('workflow-1', request);

    expect(apiFetch).toHaveBeenCalledWith('/workflows/workflow-1/run', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  });
});
