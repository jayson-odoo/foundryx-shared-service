/** Planner 3D staff wire shapes (lane PLANNER-3D-S1): keys + webhook receivers.
 *  Backend: `service_backend/modules/planner3d/schemas.py`. */

export interface Planner3dKeyItem {
  id: string;
  name: string;
  keyMasked: string;
  createdAt: string;
  lastUsedAt: string | null;
  revokedAt: string | null;
}

/** Create answer - the full key, shown ONCE. */
export interface Planner3dKeyCreated extends Planner3dKeyItem {
  key: string;
}

export type Planner3dEvent = 'model.candidates_ready' | 'model.ready';

export interface Planner3dReceiverItem {
  id: string;
  url: string;
  events: Planner3dEvent[];
  createdAt: string;
  lastSuccessAt: string | null;
}

/** Create answer - the signing secret, shown ONCE. */
export interface Planner3dReceiverCreated extends Planner3dReceiverItem {
  secret: string;
}

export const PLANNER3D_EVENT_LABELS: Record<Planner3dEvent, string> = {
  'model.candidates_ready': 'Candidate models ready',
  'model.ready': 'Approved model ready',
};
