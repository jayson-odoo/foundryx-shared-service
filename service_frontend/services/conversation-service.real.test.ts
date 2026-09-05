/**
 * Plan 27 S4 - real conversation-service coverage (AC-IVE-15/16/17/28/13/36/37).
 * Focus: the thread-list query string (server-side filtering wiring) and the
 * four plan-27 routes (close/events/shortcuts) hit the exact contract.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { realConversationService as service } from './conversation-service.real';
import type { ThreadListQuery } from '@/types/omnichannel';

const { apiFetch } = vi.hoisted(() => ({ apiFetch: vi.fn() }));

vi.mock('@/lib/api-client', async () => {
  const actual =
    await vi.importActual<typeof import('@/lib/api-client')>('@/lib/api-client');
  return { ...actual, apiFetch };
});

beforeEach(() => apiFetch.mockReset());

const BASE_QUERY: ThreadListQuery = { workspaceId: 'wsp-001' };

describe('realConversationService.listThreads', () => {
  it('sends every plan-27 dimension when present', async () => {
    apiFetch.mockResolvedValue({ data: [] });

    await service.listThreads({
      ...BASE_QUERY,
      lifecycleStageIds: ['stg-1', 'stg-2'],
      tagIds: ['tag-1'],
      channelIds: ['chn-1'],
      unreplied: true,
      sort: 'longest_waiting',
      viewId: 'view-1',
    });

    const url = apiFetch.mock.calls[0][0] as string;
    expect(url).toContain('lifecycleStageIds=stg-1%2Cstg-2');
    expect(url).toContain('tagIds=tag-1');
    expect(url).toContain('channelIds=chn-1');
    expect(url).toContain('unreplied=true');
    expect(url).toContain('sort=longest_waiting');
    expect(url).toContain('viewId=view-1');
  });

  it('omits unreplied when false and no view is active (today\'s no-op)', async () => {
    apiFetch.mockResolvedValue({ data: [] });

    await service.listThreads({ ...BASE_QUERY, unreplied: false });

    const url = apiFetch.mock.calls[0][0] as string;
    expect(url).not.toContain('unreplied');
  });

  it('sends an EXPLICIT unreplied=false when a saved view is active (AC-IVE-17 override)', async () => {
    apiFetch.mockResolvedValue({ data: [] });

    // A user picked a saved view whose stored filter has unreplied:true, then
    // toggled the Unreplied switch OFF - the explicit false MUST override the
    // view's value, so it cannot be a "falsy = omit" param while viewId is set.
    await service.listThreads({ ...BASE_QUERY, viewId: 'view-1', unreplied: false });

    const url = apiFetch.mock.calls[0][0] as string;
    expect(url).toContain('unreplied=false');
  });

  it('sends unreplied=true when a view is active and the toggle is on', async () => {
    apiFetch.mockResolvedValue({ data: [] });

    await service.listThreads({ ...BASE_QUERY, viewId: 'view-1', unreplied: true });

    const url = apiFetch.mock.calls[0][0] as string;
    expect(url).toContain('unreplied=true');
  });

  it('sends an EXPLICIT status=ALL when a view is active and Show reads All (review round 2, finding 1)', async () => {
    apiFetch.mockResolvedValue({ data: [] });

    // A saved view stores a `statuses` filter server-side; the backend
    // treats an absent `status` param as "keep the view's value" and an
    // explicit `ALL` as "clear it" - so the bar reading "All" must send
    // status=ALL, or the view's stored statuses silently win (AC-IVE-17).
    await service.listThreads({ ...BASE_QUERY, viewId: 'view-1', status: 'ALL' });

    const url = apiFetch.mock.calls[0][0] as string;
    expect(url).toContain('status=ALL');
  });

  it('sends an EXPLICIT priority=ALL when a view is active and Priority reads All (review round 2, finding 1)', async () => {
    apiFetch.mockResolvedValue({ data: [] });

    await service.listThreads({ ...BASE_QUERY, viewId: 'view-1', priority: 'ALL' });

    const url = apiFetch.mock.calls[0][0] as string;
    expect(url).toContain('priority=ALL');
  });

  it('still sends the picked status/priority when a view is active and the bar overrides them', async () => {
    apiFetch.mockResolvedValue({ data: [] });

    await service.listThreads({
      ...BASE_QUERY,
      viewId: 'view-1',
      status: 'OPEN',
      priority: 'HIGH',
    });

    const url = apiFetch.mock.calls[0][0] as string;
    expect(url).toContain('status=OPEN');
    expect(url).toContain('priority=HIGH');
  });

  it('omits status/priority when no view is active and the bar reads All (unchanged behaviour)', async () => {
    apiFetch.mockResolvedValue({ data: [] });

    await service.listThreads({ ...BASE_QUERY, status: 'ALL', priority: 'ALL' });

    const url = apiFetch.mock.calls[0][0] as string;
    expect(url).not.toContain('status=');
    expect(url).not.toContain('priority=');
  });
});

describe('realConversationService plan-27 routes', () => {
  it('closeThread posts to /close with the reason + note', async () => {
    apiFetch.mockResolvedValue({ id: 'cnt-1', status: 'CLOSED' });

    await service.closeThread('cnt-1', { closeReasonId: 'cr-1', note: 'Refunded' });

    expect(apiFetch).toHaveBeenCalledWith('/omnichannel/contacts/cnt-1/close', {
      method: 'POST',
      body: JSON.stringify({ closeReasonId: 'cr-1', note: 'Refunded' }),
    });
  });

  it('listEvents unwraps the paginated envelope', async () => {
    apiFetch.mockResolvedValue({ data: [{ id: 'evt-1' }], total: 1 });

    const events = await service.listEvents('cnt-1');

    expect(apiFetch).toHaveBeenCalledWith('/omnichannel/contacts/cnt-1/events');
    expect(events).toEqual([{ id: 'evt-1' }]);
  });

  it('listShortcuts hits the contact-scoped route', async () => {
    apiFetch.mockResolvedValue([{ workflowId: 'wf-1', name: 'Send NPS' }]);

    const shortcuts = await service.listShortcuts('cnt-1');

    expect(apiFetch).toHaveBeenCalledWith('/omnichannel/contacts/cnt-1/shortcuts');
    expect(shortcuts).toEqual([{ workflowId: 'wf-1', name: 'Send NPS' }]);
  });

  it('runShortcut POSTs to the workflow-scoped route', async () => {
    apiFetch.mockResolvedValue({ runId: 'run-1', status: 'PENDING' });

    const result = await service.runShortcut('cnt-1', 'wf-1');

    expect(apiFetch).toHaveBeenCalledWith('/omnichannel/contacts/cnt-1/shortcuts/wf-1', {
      method: 'POST',
    });
    expect(result).toEqual({ runId: 'run-1', status: 'PENDING' });
  });
});
