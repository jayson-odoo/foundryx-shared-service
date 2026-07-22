import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiFetch = vi.fn();
const apiFetchText = vi.fn();
vi.mock('@/lib/api-client', () => ({
  apiFetch: (...args: unknown[]) => apiFetch(...args),
  apiFetchText: (...args: unknown[]) => apiFetchText(...args),
}));

import { realAiService } from './ai-service.real';
import { aiService } from './ai-service';
import type { ListQuery } from '@/types/resource';

const QUERY: ListQuery = { page: 0, pageSize: 25 };

beforeEach(() => {
  vi.clearAllMocks();
  apiFetch.mockResolvedValue({ data: [], total: 0, page: 0 });
  apiFetchText.mockResolvedValue('csv');
});

describe('the shipped service is REAL-bound (Definition-of-Done #1)', () => {
  it('exports the real implementation, not the mock', () => {
    // A surviving mock behind a "done" slice is debt, not done.
    expect(aiService).toBe(realAiService);
  });
});

describe('realAiService request shapes', () => {
  it('lists agents with server-side paging params', async () => {
    await realAiService.listAgents({ ...QUERY, search: 'grill' });
    expect(apiFetch).toHaveBeenCalledWith(
      expect.stringContaining('/ai/agents?page=0&page_size=25&search=grill'),
    );
  });

  it('encodes sort direction', async () => {
    await realAiService.listTraces({ ...QUERY, sort: { id: 'created', desc: true } });
    const url = apiFetch.mock.calls[0][0] as string;
    expect(url).toContain('sort_by=created');
    expect(url).toContain('sort_dir=desc');
  });

  it('drops paging for the record-nav `at` call', async () => {
    apiFetch.mockResolvedValue({ agent: null, total: 0 });
    await realAiService.getAgentAt(QUERY, 3);
    const url = apiFetch.mock.calls[0][0] as string;
    expect(url).toContain('/ai/agents/at?');
    expect(url).toContain('index=3');
    expect(url).not.toContain('page=');
  });

  it('reads CSV export as text, not JSON', async () => {
    const csv = await realAiService.exportAgents(QUERY, ['name', 'model']);
    expect(apiFetchText).toHaveBeenCalledWith(expect.stringContaining('columns=name%2Cmodel'));
    expect(csv).toBe('csv');
  });

  it('sends the equipped skill SET as skillIds[] (AC-BI-06b)', async () => {
    apiFetch.mockResolvedValue({ id: 'a1', skills: [] });
    await realAiService.createAgent({ name: 'A', skillIds: ['s1', 's2'] });
    expect(apiFetch).toHaveBeenCalledWith('/ai/agents', {
      method: 'POST',
      body: JSON.stringify({ name: 'A', skillIds: ['s1', 's2'] }),
    });
  });

  it('url-encodes the connection id on the models probe', async () => {
    apiFetch.mockResolvedValue({ data: [], isLive: true, message: null });
    await realAiService.listModels('conn/with slash');
    expect(apiFetch).toHaveBeenCalledWith(
      '/ai/agents/models?connection_id=conn%2Fwith%20slash',
    );
  });

  it('PATCHes a skill body (which mints a new version server-side)', async () => {
    apiFetch.mockResolvedValue({ id: 's1' });
    await realAiService.updateSkill('s1', { body: 'new body' });
    expect(apiFetch).toHaveBeenCalledWith('/ai/skills/s1', {
      method: 'PATCH',
      body: JSON.stringify({ body: 'new body' }),
    });
  });

  it('POSTs a rollback as a version-id label move', async () => {
    apiFetch.mockResolvedValue({ id: 's1' });
    await realAiService.rollbackSkill('s1', 'v1');
    expect(apiFetch).toHaveBeenCalledWith('/ai/skills/s1/rollback', {
      method: 'POST',
      body: JSON.stringify({ versionId: 'v1' }),
    });
  });

  it('returns null rather than throwing when a record is missing', async () => {
    apiFetch.mockRejectedValue(new Error('404'));
    await expect(realAiService.getAgent('nope')).resolves.toBeNull();
    await expect(realAiService.getSkill('nope')).resolves.toBeNull();
    await expect(realAiService.getTrace('nope')).resolves.toBeNull();
  });

  it('posts the flag toggle', async () => {
    apiFetch.mockResolvedValue({ id: 't1', flagged: true });
    await realAiService.flagTrace('t1', true);
    expect(apiFetch).toHaveBeenCalledWith('/ai/traces/t1/flag', {
      method: 'POST',
      body: JSON.stringify({ flagged: true }),
    });
  });
});
