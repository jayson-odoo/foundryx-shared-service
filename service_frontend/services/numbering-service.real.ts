/** Real numbering service - talks to FastAPI via the shared api-client. */
import type { NumberCatalogItem, NumberFormatSet } from '@/types/numbering';
import { apiFetch } from '@/lib/api-client';
import type { NumberingService } from './numbering-service';

export const realNumberingService: NumberingService = {
  getCatalog() {
    return apiFetch<NumberCatalogItem[]>('/numbering');
  },
  async setFormat(docType: string, body: NumberFormatSet) {
    await apiFetch<void>(`/numbering/${encodeURIComponent(docType)}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    });
  },
  async setNextVal(docType: string, nextVal: number) {
    await apiFetch<void>(`/numbering/${encodeURIComponent(docType)}/next-val`, {
      method: 'PUT',
      body: JSON.stringify({ nextVal }),
    });
  },
  async resetFormat(docType: string) {
    await apiFetch<void>(`/numbering/${encodeURIComponent(docType)}`, {
      method: 'DELETE',
    });
  },
};
