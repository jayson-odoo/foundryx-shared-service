'use client';

/**
 * Realtime subscription for a workspace's conversation events (plan 05).
 * Phase A: mock timer emitter behind conversation-service; Phase B: WebSocket -
 * the hook is the stable seam, only the service implementation changes.
 */
import { useEffect, useRef } from 'react';

import { conversationService } from '@/services/conversation-service';
import type { ConversationSocketEvent } from '@/types/omnichannel';

export function useConversationSocket(
  workspaceId: string | null | undefined,
  onEvent: (event: ConversationSocketEvent) => void,
): void {
  // Keep the latest handler without resubscribing on every render.
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;

  useEffect(() => {
    if (!workspaceId) return;
    return conversationService.subscribe(workspaceId, (event) => handlerRef.current(event));
  }, [workspaceId]);
}
