/**
 * Broadcast service (plan 29, S0). UI -> hook -> service -> `lib/api-client`.
 * S0 binds the MOCK below; S1 lands the backend routes (§5.1 of the plan)
 * and S4 swaps this export to the real api-client impl in ONE line:
 *
 *   GET    /omnichannel/workspaces/{wsId}/broadcasts
 *   GET    /omnichannel/workspaces/{wsId}/broadcasts/audience-preview
 *   POST   /omnichannel/workspaces/{wsId}/broadcasts
 *   GET    /omnichannel/workspaces/{wsId}/broadcasts/{id}
 *   PATCH  /omnichannel/workspaces/{wsId}/broadcasts/{id}
 *   DELETE /omnichannel/workspaces/{wsId}/broadcasts/{id}
 *   POST   /omnichannel/workspaces/{wsId}/broadcasts/{id}/duplicate
 *   POST   /omnichannel/workspaces/{wsId}/broadcasts/{id}/send
 *   POST   /omnichannel/workspaces/{wsId}/broadcasts/{id}/cancel
 *   POST   /omnichannel/workspaces/{wsId}/broadcasts/{id}/test-send
 *   GET    /omnichannel/workspaces/{wsId}/broadcasts/{id}/recipients
 *
 * The audience is CONFIGURATION only (segment id | inline FilterGroup |
 * explicit contact ids) - snapshotted into recipient rows at SEND time, never
 * at save (D-A4-2). Bindings are structured `{source, field?, fallback?}`
 * slots, never a merge-string render (D-A4-4) - see `types/omnichannel.ts`.
 */
import type {
  Broadcast,
  BroadcastAudience,
  BroadcastRecipient,
  CreateBroadcastInput,
  UpdateBroadcastInput,
} from '@/types/omnichannel';
import type { ListQuery, ListResult } from '@/types/resource';
import { mockBroadcastService } from './broadcast-service.mock';

export interface RecipientQuery {
  page: number;
  pageSize: number;
  state?: string;
  search?: string;
}

export interface BroadcastService {
  list(workspaceId: string, query: ListQuery): Promise<ListResult<Broadcast>>;
  get(workspaceId: string, id: string): Promise<Broadcast>;
  /** SQL-computed (backend) / client-evaluated (S0 mock) resolved recipient
   *  count for the audience currently being configured - never a stored list. */
  audiencePreview(workspaceId: string, audience: BroadcastAudience): Promise<{ count: number }>;
  create(workspaceId: string, input: CreateBroadcastInput): Promise<Broadcast>;
  update(workspaceId: string, id: string, input: UpdateBroadcastInput): Promise<Broadcast>;
  remove(workspaceId: string, id: string): Promise<void>;
  duplicate(workspaceId: string, id: string): Promise<Broadcast>;
  /** `scheduledAt` unset = send now (-> SENDING); a future instant -> SCHEDULED. */
  send(workspaceId: string, id: string, scheduledAt?: string | null): Promise<Broadcast>;
  cancel(workspaceId: string, id: string): Promise<Broadcast>;
  /** One message to ONE contact through the same send path/bindings - creates
   *  no recipient row and never touches counts or status (D-A4-18). */
  testSend(workspaceId: string, id: string, contactId: string): Promise<{ messageId: string }>;
  recipients(workspaceId: string, id: string, query: RecipientQuery): Promise<ListResult<BroadcastRecipient>>;
}

// S0 MOCK - swap to real in S4 (plan 29).
export const broadcastService: BroadcastService = mockBroadcastService;
