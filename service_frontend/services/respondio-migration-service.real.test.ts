/**
 * Real respond.io migration service (plan 33 S6, AC-MIG-56) - pins the exact
 * routes/verbs against `modules/omnichannel/routers/migration.py`: the
 * multipart upload contract (S5), the job CRUD family, and the DEDICATED
 * cancel route (`POST .../jobs/{id}/cancel`, never the generic core
 * `/jobs/{id}/abort`).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { CreateMigrationJobInput } from '@/types/respondio-migration';

const apiFetchMock = vi.fn();
const apiFetchTextMock = vi.fn();
vi.mock('@/lib/api-client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api-client')>();
  return {
    ...actual,
    apiFetch: (...args: Parameters<typeof actual.apiFetch>) => apiFetchMock(...args),
    apiFetchText: (...args: Parameters<typeof actual.apiFetchText>) => apiFetchTextMock(...args),
  };
});

import { realRespondioMigrationService as svc } from './respondio-migration-service.real';

beforeEach(() => {
  apiFetchMock.mockReset();
  apiFetchTextMock.mockReset();
});

describe('realRespondioMigrationService', () => {
  it('preflight() GETs the connectionId/workspaceId query', async () => {
    apiFetchMock.mockResolvedValue({});
    await svc.preflight('conn-1', 'wsp-1');
    expect(apiFetchMock).toHaveBeenCalledWith('/omnichannel/migration/preflight?connectionId=conn-1&workspaceId=wsp-1');
  });

  it('uploadCsv() POSTs multipart with file + kind (S5, AC-MIG-46/47)', async () => {
    apiFetchMock.mockResolvedValue({ id: 'upload-1', rowCount: 3, headers: ['First Name'] });
    const file = new File(['a,b\n1,2'], 'contacts.csv', { type: 'text/csv' });
    await svc.uploadCsv('contacts', file);
    expect(apiFetchMock).toHaveBeenCalledWith(
      '/omnichannel/migration/uploads',
      expect.objectContaining({ method: 'POST' }),
    );
    const body = apiFetchMock.mock.calls[0][1].body as FormData;
    expect(body).toBeInstanceOf(FormData);
    expect(body.get('kind')).toBe('contacts');
    expect((body.get('file') as File).name).toBe('contacts.csv');
  });

  it('listJobs() forwards page/pageSize/search/sortBy/sortDir/status', async () => {
    apiFetchMock.mockResolvedValue({ data: [], total: 0 });
    await svc.listJobs({
      page: 1,
      pageSize: 25,
      search: 'acme',
      sort: { id: 'spaceLabel', desc: false },
      segment: 'done',
    });
    const url = apiFetchMock.mock.calls[0][0] as string;
    expect(url).toContain('/omnichannel/migration/jobs?');
    expect(url).toContain('page=1');
    expect(url).toContain('pageSize=25');
    expect(url).toContain('search=acme');
    expect(url).toContain('sortBy=spaceLabel');
    expect(url).toContain('sortDir=asc');
    expect(url).toContain('status=done');
  });

  it('getJob() GETs /jobs/{id}', async () => {
    apiFetchMock.mockResolvedValue({});
    await svc.getJob('mig-job-1');
    expect(apiFetchMock).toHaveBeenCalledWith('/omnichannel/migration/jobs/mig-job-1');
  });

  it('createJob() POSTs the input verbatim (source/contactsUploadId/csvHeaderMap included)', async () => {
    apiFetchMock.mockResolvedValue({});
    const input: CreateMigrationJobInput = {
      connectionId: null,
      workspaceId: 'wsp-1',
      mode: 'dry_run',
      source: 'csv',
      channelMap: [],
      userMap: [],
      teamMap: [],
      lifecycleMap: [],
      contactsUploadId: 'upload-1',
      csvHeaderMap: { firstName: 'First Name' },
    };
    await svc.createJob(input);
    expect(apiFetchMock).toHaveBeenCalledWith('/omnichannel/migration/jobs', {
      method: 'POST',
      body: JSON.stringify(input),
    });
  });

  it('cancelJob() POSTs the DEDICATED /jobs/{id}/cancel route (never the generic /jobs/{id}/abort)', async () => {
    apiFetchMock.mockResolvedValue({});
    await svc.cancelJob('mig-job-1');
    expect(apiFetchMock).toHaveBeenCalledWith('/omnichannel/migration/jobs/mig-job-1/cancel', { method: 'POST' });
  });

  it('downloadFailuresCsv() reads the authed CSV as text (D-A6-23)', async () => {
    apiFetchTextMock.mockResolvedValue('entity,sourceId,sourceLabel,reason,action\n');
    const csv = await svc.downloadFailuresCsv('mig-job-1');
    expect(apiFetchTextMock).toHaveBeenCalledWith('/omnichannel/migration/jobs/mig-job-1/failures.csv');
    expect(csv).toContain('entity,sourceId');
  });
});
