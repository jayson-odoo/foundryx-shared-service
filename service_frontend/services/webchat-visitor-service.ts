/**
 * Web chat VISITOR service (plan 34 / A7b S4) - the panel's own boundary,
 * separate from the admin-side `webchat-service.ts` trio. Every call is
 * unauthenticated-by-cookie (D-A7B-4): `startSession` needs no token (or
 * replays a stored one for renewal), every other call carries the visitor
 * token as a Bearer header the caller supplies explicitly - there is no
 * ambient session for this trio to read.
 *
 * S4 MOCK - bound to `.mock` here, mirroring `webchat-service.ts`'s own S0
 * comment exactly: the backend endpoints this trio calls
 * (`POST/GET .../session`, `POST/GET .../messages`, the visitor WS) are
 * live on :8014 as of S2/S3, but the OFFICIAL swap to `.real` happens in S6
 * (AC-WEB-63) alongside the admin trio, at this ONE export - no call site
 * changes. (S4's own live-verify evidence flips this export to
 * `realWebchatVisitorService` locally for the recorded run and reverts it
 * before commit - see the S4 commit body.)
 */
import type {
  PostVisitorMessageInput,
  VisitorMessage,
  VisitorMessagesPage,
  WebchatSessionResult,
} from '@/types/omnichannel';
import { mockWebchatVisitorService } from './webchat-visitor-service.mock';

export interface WebchatVisitorService {
  /** Mint a fresh session, or renew/resume one from a stored token
   *  (AC-WEB-23..25/28/29/49/50). `token=null` for a brand-new visitor. */
  startSession(widgetKey: string, token: string | null): Promise<WebchatSessionResult>;
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

// S4 MOCK - swap to real in S6 (AC-WEB-63).
export const webchatVisitorService: WebchatVisitorService = mockWebchatVisitorService;
