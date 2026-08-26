import { describe, expect, it } from 'vitest';
import { mockWorkflowService } from './workflow-service.mock';

describe('mockWorkflowService', () => {
  it('provides deterministic safe sources for workflow test options', async () => {
    await expect(mockWorkflowService.getTestOptions('wf-welcome')).resolves.toEqual({
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
  });
});
