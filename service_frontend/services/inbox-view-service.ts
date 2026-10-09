/**
 * Inbox-view (saved view) service - the boundary the view rail's "Save view"
 * dialog and the rail's Views section talk to (plan 27, §5.1).
 *
 * Real backend since plan 27 S4. The interface IS the backend contract:
 *
 *   GET    /omnichannel/workspaces/{wsId}/inbox-views          (conversations.read)
 *   POST   /omnichannel/workspaces/{wsId}/inbox-views          (own: conversations.read;
 *                                                                shared: + inbox_views.manage)
 *   PATCH  /omnichannel/workspaces/{wsId}/inbox-views/{id}     (same split, D-A3-11)
 *   DELETE /omnichannel/workspaces/{wsId}/inbox-views/{id}
 *
 * List returns the caller's own views plus shared views, `sortOrder` first
 * (AC-IVE-18); a personal view needs only `conversations.read` to create/
 * edit/delete - `isShared` (or editing someone else's view) additionally
 * needs `inbox_views.manage` (D-A3-11, enforced server-side; the frontend
 * only hides the Shared switch per `useCan`). Cap 50 per workspace, name
 * unique per workspace case-insensitively.
 */
import type { CreateInboxViewInput, InboxView, UpdateInboxViewInput } from '@/types/omnichannel';
import { realInboxViewService } from './inbox-view-service.real';

export interface InboxViewService {
  list(workspaceId: string): Promise<InboxView[]>;
  create(workspaceId: string, input: CreateInboxViewInput): Promise<InboxView>;
  update(workspaceId: string, id: string, input: UpdateInboxViewInput): Promise<InboxView>;
  remove(workspaceId: string, id: string): Promise<void>;
}

// Real backend since plan 27 S4 (routes live since S2).
export const inboxViewService: InboxViewService = realInboxViewService;
