/**
 * Real Planner 3D service - FastAPI staff routes under `/planner3d`
 * (`service_backend/modules/planner3d/routers/staff.py`).
 */
import { apiFetch } from '@/lib/api-client';
import type {
  Planner3dKeyCreated,
  Planner3dKeyItem,
  Planner3dReceiverCreated,
  Planner3dReceiverItem,
} from '@/types/planner3d';
import type { Planner3dService } from './planner3d-service';

const BASE = '/planner3d';

export const realPlanner3dService: Planner3dService = {
  async listKeys() {
    const res = await apiFetch<{ data: Planner3dKeyItem[] }>(`${BASE}/keys`);
    return res.data;
  },
  createKey(name) {
    return apiFetch<Planner3dKeyCreated>(`${BASE}/keys`, {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
  },
  async listReceivers() {
    const res = await apiFetch<{ data: Planner3dReceiverItem[] }>(`${BASE}/receivers`);
    return res.data;
  },
  createReceiver(url, events) {
    return apiFetch<Planner3dReceiverCreated>(`${BASE}/receivers`, {
      method: 'POST',
      body: JSON.stringify({ url, events }),
    });
  },
};
