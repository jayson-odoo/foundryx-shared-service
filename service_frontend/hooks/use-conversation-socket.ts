'use client';

/**
 * Realtime subscription for a workspace's conversation events (plan 05).
 * Phase A: mock timer emitter behind conversation-service; Phase B: WebSocket -
 * the hook is the stable seam, only the service implementation changes.
 * `onConnectionChange` (optional) hears whether the feed is connected; it
 * never changes the subscription itself.
 */
import { useEffect, useRef } from 'react';
import type { ConversationSocketEvent } from '@/types/omnichannel';
import { conversationService } from '@/services/conversation-service';

export function useConversationSocket(
  workspaceId: string | null | undefined,
  onEvent: (event: ConversationSocketEvent) => void,
  onConnectionChange?: (connected: boolean) => void,
): void {
  // Keep the latest handler without resubscribing on every render.
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;
  const connectionRef = useRef(onConnectionChange);
  connectionRef.current = onConnectionChange;

  useEffect(() => {
    if (!workspaceId) return;
    return conversationService.subscribe(
      workspaceId,
      (event) => handlerRef.current(event),
      (connected) => connectionRef.current?.(connected),
    );
  }, [workspaceId]);
}
