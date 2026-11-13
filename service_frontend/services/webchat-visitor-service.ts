/**
 * Web chat VISITOR service (plan 34 / A7b S4) - the panel's own boundary,
 * separate from the admin-side `webchat-service.ts` trio. Every call is
 * unauthenticated-by-cookie (D-A7B-4): the visitor token travels as a Bearer
 * header the caller supplies explicitly - there is no ambient session for
 * this trio to read.
 *
 * Amended 2026-09-09 (BL-SS-183): there is no `startSession` here. Session
 * start is the LOADER's call (vanilla JS in the customer's own top-level
 * page, `modules/omnichannel/widget/loader.js`), because only a fetch from
 * that document carries the embedding website's `Origin` - the value the
 * channel's allowlist is about. This trio only ever serves a session the
 * loader already minted.
 *
 * Plan 34 / A7b, S6 (AC-WEB-63) - bound to `realWebchatVisitorService`
 * below, the OFFICIAL swap alongside the admin trio at this ONE export - no
 * call site changes. (S4's own live-verify evidence flipped this export
 * locally for a recorded run and reverted it before commit - see the S4
 * commit body; this is the first time the flip is permanent.)
 */
import type {
  PostVisitorMessageInput,
  VisitorMessage,
  VisitorMessagesPage,
} from '@/types/omnichannel';
import { realWebchatVisitorService } from './webchat-visitor-service.real';

export interface WebchatVisitorService {
  /** The ONE write on the visitor surface. Returns `null` when the honeypot
   *  fired (AC-WEB-32) - a real visitor's browser never triggers this. */
  sendMessage(
    widgetKey: string,
    token: string,
    input: PostVisitorMessageInput,
  ): Promise<VisitorMessage | null>;
  /** History AND the poll fallback (D-A7B-16, the SAME endpoint). */
  listMessages(widgetKey: string, token: string, after?: string | null): Promise<VisitorMessagesPage>;
  /**
   * Realtime relay for this visitor's own contact (AC-WEB-38..40). Returns
   * an unsubscribe function. `onStatus` lets the caller drive the poll
   * fallback (D-A7B-16): poll while `'closed'`/`'connecting'`, stop while
   * `'open'`. The mock never opens (`'closed'` forever, no real transport),
   * matching a real socket that never connects.
   */
  subscribe(
    workspaceId: string,
    token: string,
    onMessage: (message: VisitorMessage) => void,
    onStatus?: (status: 'connecting' | 'open' | 'closed') => void,
  ): () => void;
}

export const webchatVisitorService: WebchatVisitorService = realWebchatVisitorService;
