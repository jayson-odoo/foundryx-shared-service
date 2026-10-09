/**
 * Real contact-list service (plan 26 S4, AC-CTM-46) - camelCase list query
 * params (`pageSize`/`sortBy`/`sortDir`/`segment`, NOT `user-service.real.ts`'s
 * snake_case), the "all contacts" segment sentinel dropped before the wire
 * (the backend 404s `SegmentNotFound` for any unrecognized id), `getAt`'s
 * client-side page math (no dedicated `/contacts/at` endpoint), and the
 * export job's poll -> download flow (D-A2-6a: pending -> done -> file, plus
 * the failed-job and the wait-window-exceeded `ExportPendingError` paths).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ExportPendingError } from '@/lib/service-errors';
import type { ContactListItem } from '@/types/omnichannel';
import type { Job } from '@/types/jobs';

const apiFetchMock = vi.fn();
const apiFetchBlobMock = vi.fn();

vi.mock('@/lib/api-client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api-client')>();
  return {
    ...actual,
    apiFetch: (...args: Parameters<typeof actual.apiFetch>) => apiFetchMock(...args),
    apiFetchBlob: (...args: Parameters<typeof actual.apiFetchBlob>) => apiFetchBlobMock(...args),
  };
});

import { ApiError } from '@/lib/api-client';
import { realContactService } from './contact-service.real';

function contactRow(id: string): ContactListItem {
  return {
    id,
    tenantId: 't1',
    workspaceId: 'wsp-1',
    name: 'Ada Lovelace',
    firstName: 'Ada',
    lastName: 'Lovelace',
    phone: '+60123456789',
    email: null,
    language: null,
    countryCode: null,
    avatarUrl: null,
    assignedUserId: null,
    assignedUserName: null,
    status: 'OPEN',
    priority: 'MEDIUM',
    channelId: null,
    channelType: 'WHATSAPP',
    cswExpiresAt: null,
    windowExpiresAt: null,
    humanAgentExpiresAt: null,
    lastIncomingMessageAt: null,
    lastMessageAt: null,
    lastMessagePreview: null,
    unreadCount: 0,
    customFields: {},
    tags: [],
    lifecycle: null,
    createdAt: '2026-01-01T00:00:00Z',
    channels: [],
  };
}

function job(overrides: Partial<Job>): Job {
  return {
    id: 'job-1',
    tenantId: 't1',
    type: 'omnichannel.contacts_export',
    status: 'pending',
    actorUserId: null,
    payload: null,
    result: null,
    logs: null,
    progressTotal: 0,
    progressDone: 0,
    progressFailed: 0,
    error: null,
    createdAt: '2026-01-01T00:00:00Z',
    startedAt: null,
    finishedAt: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('realContactService.list', () => {
  it('sends camelCase query params (pageSize/sortBy/sortDir), never snake_case', async () => {
    apiFetchMock.mockResolvedValue({ data: [], total: 0, page: 0 });
    await realContactService.list('wsp-1', {
      page: 2,
      pageSize: 25,
      search: 'ada',
      sort: { id: 'name', desc: true },
      filter: null,
    });
    const [path] = apiFetchMock.mock.calls[0];
    const [base, qs] = (path as string).split('?');
    expect(base).toBe('/omnichannel/workspaces/wsp-1/contacts');
    const params = new URLSearchParams(qs);
    expect(params.get('page')).toBe('2');
    expect(params.get('pageSize')).toBe('25');
    expect(params.get('search')).toBe('ada');
    expect(params.get('sortBy')).toBe('name');
    expect(params.get('sortDir')).toBe('desc');
    expect(params.has('sort_by')).toBe(false);
    expect(params.has('page_size')).toBe(false);
  });

  it('drops the "all contacts" segment sentinel - the backend has no segment named "all"', async () => {
    apiFetchMock.mockResolvedValue({ data: [], total: 0, page: 0 });
    await realContactService.list('wsp-1', { page: 0, pageSize: 25, segment: 'all' });
    const [path] = apiFetchMock.mock.calls[0];
    expect(new URLSearchParams((path as string).split('?')[1]).has('segment')).toBe(false);
  });

  it('forwards a real saved-segment id as-is', async () => {
    apiFetchMock.mockResolvedValue({ data: [], total: 0, page: 0 });
    await realContactService.list('wsp-1', { page: 0, pageSize: 25, segment: 'seg-1' });
    const [path] = apiFetchMock.mock.calls[0];
    expect(new URLSearchParams((path as string).split('?')[1]).get('segment')).toBe('seg-1');
  });

  it('JSON-encodes the filter tree', async () => {
    apiFetchMock.mockResolvedValue({ data: [], total: 0, page: 0 });
    const filter = { kind: 'group' as const, combinator: 'and' as const, rules: [] };
    await realContactService.list('wsp-1', { page: 0, pageSize: 25, filter });
    const [path] = apiFetchMock.mock.calls[0];
    const raw = new URLSearchParams((path as string).split('?')[1]).get('filter');
    expect(JSON.parse(raw!)).toEqual(filter);
  });
});

describe('realContactService.getAt', () => {
  it('computes the page containing the requested index from the SAME query', async () => {
    apiFetchMock.mockResolvedValue({
      data: [contactRow('cnt-21'), contactRow('cnt-22'), contactRow('cnt-23'), contactRow('cnt-24')],
      total: 40,
      page: 2,
    });
    const { contact, total } = await realContactService.getAt(
      'wsp-1',
      { page: 0, pageSize: 10, search: 'ada' },
      23,
    );
    expect(contact?.id).toBe('cnt-24');
    expect(total).toBe(40);
    const [path] = apiFetchMock.mock.calls[0];
    const params = new URLSearchParams((path as string).split('?')[1]);
    expect(params.get('page')).toBe('2'); // floor(23/10)
    expect(params.get('pageSize')).toBe('10');
    expect(params.get('search')).toBe('ada');
  });

  it('returns null when the index falls past the last page', async () => {
    apiFetchMock.mockResolvedValue({ data: [], total: 5, page: 0 });
    const { contact } = await realContactService.getAt('wsp-1', { page: 0, pageSize: 10 }, 99);
    expect(contact).toBeNull();
  });
});

describe('realContactService.exportContacts', () => {
  const req = { columns: ['id', 'name'] };

  it('polls until the job is done, then downloads + returns the CSV text', async () => {
    apiFetchMock.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === '/omnichannel/workspaces/wsp-1/contacts/export' && init?.method === 'POST') {
        return { jobId: 'job-1' };
      }
      if (path === '/jobs/job-1') return job({ status: 'done' });
      throw new Error(`unexpected apiFetch call: ${path}`);
    });
    apiFetchBlobMock.mockResolvedValue(new Blob(['id,name\n1,Ada'], { type: 'text/csv' }));

    const csv = await realContactService.exportContacts('wsp-1', req);

    expect(csv).toBe('id,name\n1,Ada');
    expect(apiFetchBlobMock).toHaveBeenCalledWith(
      '/omnichannel/workspaces/wsp-1/contacts/export/job-1/file',
    );
  });

  it('drops the "all contacts" segment sentinel on the export request body too', async () => {
    apiFetchMock.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === '/omnichannel/workspaces/wsp-1/contacts/export' && init?.method === 'POST') {
        return { jobId: 'job-1' };
      }
      return job({ status: 'done' });
    });
    apiFetchBlobMock.mockResolvedValue(new Blob(['id'], { type: 'text/csv' }));

    await realContactService.exportContacts('wsp-1', { ...req, segment: 'all' });

    const [, init] = apiFetchMock.mock.calls[0];
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.segment).toBeUndefined();
  });

  it('polls a few times before a slow job finishes (never a false pending)', async () => {
    let polls = 0;
    apiFetchMock.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === '/omnichannel/workspaces/wsp-1/contacts/export' && init?.method === 'POST') {
        return { jobId: 'job-1' };
      }
      polls += 1;
      return job({ status: polls < 3 ? 'running' : 'done' });
    });
    apiFetchBlobMock.mockResolvedValue(new Blob(['id'], { type: 'text/csv' }));

    await expect(realContactService.exportContacts('wsp-1', req)).resolves.toBe('id');
    expect(polls).toBe(3);
  });

  it('throws ExportPendingError (never a silent failure) when the wait window elapses', async () => {
    apiFetchMock.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === '/omnichannel/workspaces/wsp-1/contacts/export' && init?.method === 'POST') {
        return { jobId: 'job-1' };
      }
      return job({ status: 'running' }); // never finishes inside the window
    });

    const error = await realContactService.exportContacts('wsp-1', req).catch((e) => e);
    expect(error).toBeInstanceOf(ExportPendingError);
    expect((error as ExportPendingError).jobId).toBe('job-1');
    expect(apiFetchBlobMock).not.toHaveBeenCalled();
  });

  it('raises the job error when the export job itself failed', async () => {
    apiFetchMock.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === '/omnichannel/workspaces/wsp-1/contacts/export' && init?.method === 'POST') {
        return { jobId: 'job-1' };
      }
      return job({ status: 'failed', error: 'Row limit exceeded.' });
    });

    const error = await realContactService.exportContacts('wsp-1', req).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toBe('Row limit exceeded.');
    expect(apiFetchBlobMock).not.toHaveBeenCalled();
  });
});
