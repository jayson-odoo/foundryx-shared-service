/**
 * Real Business Requirement service - talks to FastAPI shared-service via the
 * shared api-client (Phase B-i slice 2). Endpoint map:
 * - list        → GET    /ideation/business-requirements?filter=&productId=&search=
 * - get         → GET    /ideation/business-requirements/{id}
 * - create      → POST   /ideation/business-requirements
 * - update      → PATCH  /ideation/business-requirements/{id}
 * - setStatus   → POST   /ideation/business-requirements/{id}/status  {status}
 * - listIdeas   → GET    /ideation/business-requirements/{id}/ideas
 * - linkIdeas   → POST   /ideation/business-requirements/{id}/ideas   {ideaIds}
 * - unlinkIdea  → DELETE /ideation/business-requirements/{id}/ideas/{ideaId}
 * - listVersions→ GET    /ideation/business-requirements/{id}/versions
 * - remove      → DELETE /ideation/business-requirements/{id}          (204)
 */
import { apiFetch } from '@/lib/api-client';
import type { Idea } from '@/types/ideation';
import type { StatusGraph } from '@/types/status-engine';
import type {
  BrTemplateVersion,
  BusinessRequirement,
  BusinessRequirementDetail,
} from '@/types/business-requirement';
import type { BrListFilter, BusinessRequirementService } from './business-requirement-service';

const base = '/ideation/business-requirements';
const one = (id: string) => `${base}/${encodeURIComponent(id)}`;

function listQuery(params?: BrListFilter): string {
  const p = new URLSearchParams();
  if (params?.filter) p.set('filter', params.filter);
  if (params?.productId) p.set('productId', params.productId);
  if (params?.search) p.set('search', params.search);
  const q = p.toString();
  return q ? `?${q}` : '';
}

export const realBusinessRequirementService: BusinessRequirementService = {
  list(params) {
    return apiFetch<BusinessRequirement[]>(`${base}${listQuery(params)}`);
  },

  get(id) {
    return apiFetch<BusinessRequirementDetail>(one(id));
  },

  create(input) {
    return apiFetch<BusinessRequirementDetail>(base, {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },

  update(id, input) {
    return apiFetch<BusinessRequirementDetail>(one(id), {
      method: 'PATCH',
      body: JSON.stringify(input),
    });
  },

  setStatus(id, status) {
    return apiFetch<BusinessRequirementDetail>(`${one(id)}/status`, {
      method: 'POST',
      body: JSON.stringify({ status }),
    });
  },

  statusGraph() {
    return apiFetch<StatusGraph>(`${base}/status-graph`);
  },

  listIdeas(id) {
    return apiFetch<Idea[]>(`${one(id)}/ideas`);
  },

  listForIdea(ideaId) {
    return apiFetch<BusinessRequirement[]>(
      `/ideation/ideas/${encodeURIComponent(ideaId)}/business-requirements`,
    );
  },

  linkIdeas(id, ideaIds) {
    return apiFetch<Idea[]>(`${one(id)}/ideas`, {
      method: 'POST',
      body: JSON.stringify({ ideaIds }),
    });
  },

  unlinkIdea(id, ideaId) {
    return apiFetch<Idea[]>(`${one(id)}/ideas/${encodeURIComponent(ideaId)}`, {
      method: 'DELETE',
    });
  },

  listVersions(id) {
    return apiFetch<BrTemplateVersion[]>(`${one(id)}/versions`);
  },

  remove(id) {
    return apiFetch<void>(one(id), { method: 'DELETE' });
  },
};
