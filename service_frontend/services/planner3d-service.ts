/**
 * Planner 3D service - the boundary the 3D Planner Keys and Receivers screens
 * talk to (lane PLANNER-3D-S1). The barrel binds the REAL api-client
 * implementation. Every call is the signed-in tenant's own data (the backend
 * scopes by the JWT).
 */
import type {
  Planner3dEvent,
  Planner3dKeyCreated,
  Planner3dKeyItem,
  Planner3dReceiverCreated,
  Planner3dReceiverItem,
} from '@/types/planner3d';
import { realPlanner3dService } from './planner3d-service.real';

export interface Planner3dService {
  listKeys(): Promise<Planner3dKeyItem[]>;
  /** Returns the full key ONCE. */
  createKey(name: string): Promise<Planner3dKeyCreated>;
  listReceivers(): Promise<Planner3dReceiverItem[]>;
  /** Returns the signing secret ONCE. */
  createReceiver(url: string, events: Planner3dEvent[]): Promise<Planner3dReceiverCreated>;
}

export const planner3dService: Planner3dService = realPlanner3dService;
