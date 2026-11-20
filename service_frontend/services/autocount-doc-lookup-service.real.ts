import { apiFetch } from '@/lib/api-client';
import type {
  DocLookupJob,
  DocLookupSettings,
  DocLookupStartInput,
  DocLookupStored,
  DocLookupType,
} from '@/types/autocount-doc-lookup';
import type { AutocountDocLookupService } from './autocount-doc-lookup-service';

const BASE = '/autocount/doc-lookup';

export const realAutocountDocLookupService: AutocountDocLookupService = {
  async listTypes(companyId?: string | null): Promise<DocLookupType[]> {
    const query = companyId ? `?${new URLSearchParams({ companyId }).toString()}` : '';
    const body = await apiFetch<{ data: DocLookupType[] }>(`${BASE}/types${query}`);
    return body.data;
  },

  stored(companyId: string, docNo: string, docType?: string | null): Promise<DocLookupStored> {
    const params = new URLSearchParams({ companyId, docNo });
    if (docType) params.set('docType', docType);
    return apiFetch<DocLookupStored>(`${BASE}/stored?${params.toString()}`);
  },

  start(input: DocLookupStartInput): Promise<DocLookupJob> {
    return apiFetch<DocLookupJob>(BASE, { method: 'POST', body: JSON.stringify(input) });
  },

  getJob(jobId: string): Promise<DocLookupJob> {
    return apiFetch<DocLookupJob>(`${BASE}/jobs/${encodeURIComponent(jobId)}`);
  },

  stop(jobId: string): Promise<DocLookupJob> {
    return apiFetch<DocLookupJob>(`${BASE}/jobs/${encodeURIComponent(jobId)}/stop`, {
      method: 'POST',
    });
  },

  getSettings(companyId: string): Promise<DocLookupSettings> {
    return apiFetch<DocLookupSettings>(
      `${BASE}/settings?${new URLSearchParams({ companyId }).toString()}`,
    );
  },

  saveSettings(input: DocLookupSettings): Promise<DocLookupSettings> {
    return apiFetch<DocLookupSettings>(`${BASE}/settings`, {
      method: 'PUT',
      body: JSON.stringify(input),
    });
  },
};
