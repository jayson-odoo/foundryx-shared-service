/**
 * Plan 56 C, AC-56-52 - `eraseContact(contactId)` on the contact service, real and mock.
 * Real: DELETE /omnichannel/contacts/{id} (the staff route of AC-56-51); components never fetch.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiFetchMock = vi.fn();
vi.mock('@/lib/api-client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api-client')>();
  return { ...actual, apiFetch: (...args: Parameters<typeof actual.apiFetch>) => apiFetchMock(...args) };
});

import { ApiError } from '@/lib/api-client';
import { realContactService } from './contact-service.real';
import { mockContactService, __mockResetContacts } from './contact-service.mock';

beforeEach(() => {
  vi.clearAllMocks();
  __mockResetContacts();
});

describe('realContactService.eraseContact', () => {
  it('issues DELETE /omnichannel/contacts/{id} and returns the counts body', async () => {
    const body = { contactId: 'cnt-1', erasedAt: '2026-11-04T00:00:00Z', messages: 14, files: 4 };
    apiFetchMock.mockResolvedValue(body);
    await expect(realContactService.eraseContact('cnt-1')).resolves.toEqual(body);
    const [path, init] = apiFetchMock.mock.calls[0];
    expect(path).toBe('/omnichannel/contacts/cnt-1');
    expect(init).toMatchObject({ method: 'DELETE' });
  });

  it('encodes the id and lets an ApiError (404/403) through unchanged', async () => {
    apiFetchMock.mockRejectedValue(new ApiError('Forbidden', 403));
    await expect(realContactService.eraseContact('a/b')).rejects.toMatchObject({ status: 403 });
    expect(apiFetchMock.mock.calls[0][0]).toBe('/omnichannel/contacts/a%2Fb');
  });
});

describe('mockContactService.eraseContact', () => {
  it('removes the contact from the list and answers the counts', async () => {
    const query = { page: 0, pageSize: 100, search: '', sort: null, filter: null };
    const before = await mockContactService.list('wsp-001', query);
    const target = before.data[0];
    const res = await mockContactService.eraseContact(target.id);
    expect(res.contactId).toBe(target.id);
    expect(typeof res.erasedAt).toBe('string');
    expect(res.messages).toBeGreaterThanOrEqual(0);
    expect(res.files).toBeGreaterThanOrEqual(0);
    const after = await mockContactService.list('wsp-001', query);
    expect(after.total).toBe(before.total - 1);
    expect(after.data.map((r) => r.id)).not.toContain(target.id);
  });

  it('a second erase of the same contact is a 404', async () => {
    const query = { page: 0, pageSize: 100, search: '', sort: null, filter: null };
    const id = (await mockContactService.list('wsp-001', query)).data[0].id;
    await mockContactService.eraseContact(id);
    await expect(mockContactService.eraseContact(id)).rejects.toMatchObject({ status: 404 });
  });
});
