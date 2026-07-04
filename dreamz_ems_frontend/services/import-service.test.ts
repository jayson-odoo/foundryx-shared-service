import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiFetch = vi.fn();
const apiFetchBlob = vi.fn();
vi.mock('@/lib/api-client', () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
  apiFetchBlob: (...a: unknown[]) => apiFetchBlob(...a),
}));

import { realImportService } from './import-service.real';

beforeEach(() => {
  vi.clearAllMocks();
  apiFetch.mockResolvedValue({});
  apiFetchBlob.mockResolvedValue(new Blob());
});

describe('realImportService', () => {
  it('create() sends multipart FormData with the right fields', async () => {
    const file = new File(['Email\n'], 'u.csv', { type: 'text/csv' });
    await realImportService.create({
      entityType: 'user',
      mode: 'upsert',
      abortOnInvalid: true,
      triggerAutomations: false,
      context: { projectId: 'p1' },
      file,
    });
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe('/imports');
    expect(init.method).toBe('POST');
    const form = init.body as FormData;
    expect(form.get('entityType')).toBe('user');
    expect(form.get('mode')).toBe('upsert');
    expect(form.get('abortOnInvalid')).toBe('true');
    expect(form.get('context')).toBe('{"projectId":"p1"}');
    expect(form.get('file')).toBeInstanceOf(File);
  });

  it('downloadTemplate() builds the columns+format query and fetches a blob', async () => {
    await realImportService.downloadTemplate('user', ['email', 'name'], 'xlsx');
    expect(apiFetchBlob).toHaveBeenCalledWith(
      '/imports/template/user?columns=email%2Cname&format=xlsx',
    );
  });

  it('setMapping() PUTs the mapping + sheetName', async () => {
    await realImportService.setMapping('j1', { Email: 'email', Extra: null }, 'Sheet2');
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe('/imports/j1/mapping');
    expect(init.method).toBe('PUT');
    expect(JSON.parse(init.body)).toEqual({
      mapping: { Email: 'email', Extra: null },
      sheetName: 'Sheet2',
      context: null,
    });
  });

  it('setMapping() forwards job-level context (Ticket mode)', async () => {
    await realImportService.setMapping('j1', { E: 'profile' }, undefined, {
      ticket_mode: 'paid',
      offering_id: 'o1',
      bill_to_client_id: 'c1',
    });
    const init = apiFetch.mock.calls[0][1];
    expect(JSON.parse(init.body).context).toEqual({
      ticket_mode: 'paid',
      offering_id: 'o1',
      bill_to_client_id: 'c1',
    });
  });

  it('list() encodes pagination + filters', async () => {
    await realImportService.list({ entityType: 'user', status: 'done', page: 2, pageSize: 50 });
    expect(apiFetch.mock.calls[0][0]).toBe(
      '/imports?entityType=user&status=done&page=2&page_size=50',
    );
  });

  it('commit() POSTs to the commit endpoint', async () => {
    await realImportService.commit('j9');
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe('/imports/j9/commit');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({
      abortOnInvalid: null,
      triggerAutomations: null,
      context: null,
    });
  });

  it('commit() forwards Ticket-mode context', async () => {
    await realImportService.commit('j9', {
      abortOnInvalid: false,
      triggerAutomations: false,
      context: { ticket_mode: 'comp', offering_id: 'o2' },
    });
    const init = apiFetch.mock.calls[0][1];
    expect(JSON.parse(init.body).context).toEqual({
      ticket_mode: 'comp',
      offering_id: 'o2',
    });
  });
});
