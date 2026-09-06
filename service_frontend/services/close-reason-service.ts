/**
 * Close-reason service - the boundary the workspace "Close reasons" tab and
 * the drawer's Close dialog talk to (plan 27, §5.1).
 *
 * Real backend since plan 27 S4 - `close-reason-service.real.ts` is written
 * against the exact contract below. The interface IS the backend contract:
 *
 *   GET    /omnichannel/workspaces/{wsId}/close-reasons        (conversations.read)
 *   POST   /omnichannel/workspaces/{wsId}/close-reasons        (close_reasons.manage)
 *   PATCH  /omnichannel/workspaces/{wsId}/close-reasons/{id}   (close_reasons.manage)
 *   DELETE /omnichannel/workspaces/{wsId}/close-reasons/{id}   -> 204 | 409 close_reason_in_use
 *
 * `name` required, unique per workspace case-insensitively, cap 100 (AC-IVE-25).
 * A reason referenced by any event 409s on delete - the UI offers Deactivate
 * (`isActive: false`) instead (AC-IVE-26, D-A3-13). No code ever looks a
 * reason up by name (AC-IVE-27).
 */
import type { CloseReason, CreateCloseReasonInput, UpdateCloseReasonInput } from '@/types/omnichannel';
import { realCloseReasonService } from './close-reason-service.real';

export interface CloseReasonService {
  list(workspaceId: string): Promise<CloseReason[]>;
  create(workspaceId: string, input: CreateCloseReasonInput): Promise<CloseReason>;
  update(workspaceId: string, id: string, input: UpdateCloseReasonInput): Promise<CloseReason>;
  remove(workspaceId: string, id: string): Promise<void>;
}

// Real backend since plan 27 S4 (routes live since S2).
export const closeReasonService: CloseReasonService = realCloseReasonService;
