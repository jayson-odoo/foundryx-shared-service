/**
 * Real quick-reply service — talks to FastAPI via the shared api-client.
 * Reads gated `conversations.read`; writes gated `workspaces.manage`.
 */
import { apiFetch } from '@/lib/api-client';
import type { QuickReply } from '@/types/omnichannel';
import type {
  QuickReplyCreateInput,
  QuickReplyService,
  QuickReplyUpdateInput,
} from './quick-reply-service';

function base(workspaceId: string): string {
  return `/omnichannel/workspaces/${encodeURIComponent(workspaceId)}/quick-replies`;
}

export const realQuickReplyService: QuickReplyService = {
  list(workspaceId) {
    return apiFetch<QuickReply[]>(base(workspaceId));
  },
  create(workspaceId, input: QuickReplyCreateInput) {
    return apiFetch<QuickReply>(base(workspaceId), {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },
  update(workspaceId, id, input: QuickReplyUpdateInput) {
    return apiFetch<QuickReply>(`${base(workspaceId)}/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(input),
    });
  },
  async remove(workspaceId, id) {
    await apiFetch<void>(`${base(workspaceId)}/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    });
  },
};
