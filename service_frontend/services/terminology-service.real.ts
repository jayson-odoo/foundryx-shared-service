/** Real terminology service - talks to FastAPI via the shared api-client. */
import type { TermCatalogItem, TermLabels, TerminologyMap } from '@/types/terminology';
import { apiFetch } from '@/lib/api-client';
import type { TerminologyService } from './terminology-service';

export const realTerminologyService: TerminologyService = {
  getTerminology() {
    return apiFetch<TerminologyMap>('/terminology');
  },
  getCatalog() {
    return apiFetch<TermCatalogItem[]>('/terminology/catalog');
  },
  setTerm(key: string, labels: TermLabels) {
    return apiFetch<TermLabels>(`/terminology/${encodeURIComponent(key)}`, {
      method: 'PUT',
      body: JSON.stringify(labels),
    });
  },
  async resetTerm(key: string) {
    await apiFetch<void>(`/terminology/${encodeURIComponent(key)}`, {
      method: 'DELETE',
    });
  },
};
