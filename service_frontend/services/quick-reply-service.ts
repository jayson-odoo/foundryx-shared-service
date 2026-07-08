/**
 * Quick-reply (canned response) service — the boundary the UI talks to (plan
 * sprint-3/12). The composer's ★ picker consumes the same rows via
 * `conversation-service`; this service manages them (create/edit/delete).
 * Frontend-first bound the mock; the shipped page binds the REAL api-client impl
 * (swap is the ONE line at the bottom). The interface IS the backend contract
 * (`/omnichannel/workspaces/{ws}/quick-replies`).
 */
import type { QuickReply } from '@/types/omnichannel';
import { realQuickReplyService } from './quick-reply-service.real';

/** Create payload. `body` required (backend rejects blank); `shortcut` optional. */
export interface QuickReplyCreateInput {
  shortcut?: string | null;
  body: string;
}

/**
 * Update payload. Omitted keys keep the current value; an explicit `shortcut:
 * null` clears the shortcut. `body` when present must be non-blank.
 */
export interface QuickReplyUpdateInput {
  shortcut?: string | null;
  body?: string;
}

export interface QuickReplyService {
  /** All quick replies for a workspace (shortcut-sorted, nulls last). */
  list(workspaceId: string): Promise<QuickReply[]>;
  /** Create a quick reply in a workspace. */
  create(workspaceId: string, input: QuickReplyCreateInput): Promise<QuickReply>;
  /** Update a quick reply. */
  update(
    workspaceId: string,
    id: string,
    input: QuickReplyUpdateInput,
  ): Promise<QuickReply>;
  /** Delete a quick reply. */
  remove(workspaceId: string, id: string): Promise<void>;
}

// Phase B: real api-client implementation. (Mock retained in *.mock.ts.)
export const quickReplyService: QuickReplyService = realQuickReplyService;
