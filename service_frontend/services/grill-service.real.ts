/**
 * Real grill service — talks to FastAPI shared-service via the shared
 * api-client (Phase B-i slice 3). Endpoint map:
 * - state    → GET  /ideation/business-requirements/{id}/grill
 * - open     → POST /ideation/business-requirements/{id}/grill/open
 * - turn     → POST /ideation/business-requirements/{id}/grill/turn     {message}
 * - generate → POST /ideation/business-requirements/{id}/grill/generate
 */
import { apiFetch } from '@/lib/api-client';
import type { GrillGenerate, GrillState, GrillTurn } from '@/types/grill';
import type { GrillService } from './grill-service';

const one = (id: string) =>
  `/ideation/business-requirements/${encodeURIComponent(id)}/grill`;

export const realGrillService: GrillService = {
  state(brId) {
    return apiFetch<GrillState>(one(brId));
  },

  open(brId) {
    return apiFetch<GrillTurn>(`${one(brId)}/open`, {
      method: 'POST',
    });
  },

  turn(brId, message) {
    return apiFetch<GrillTurn>(`${one(brId)}/turn`, {
      method: 'POST',
      body: JSON.stringify({ message }),
    });
  },

  generate(brId) {
    return apiFetch<GrillGenerate>(`${one(brId)}/generate`, {
      method: 'POST',
    });
  },
};
