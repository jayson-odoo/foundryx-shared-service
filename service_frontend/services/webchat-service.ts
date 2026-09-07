/**
 * Web chat channel service (admin side, plan 34 / A7b). Provisions a
 * `WEBCHAT` channel, reads/writes its widget configuration, and rotates its
 * signing secret. Mirrors `channel-service.ts`'s trio shape (`.mock`/`.real`,
 * one boundary swap).
 *
 * S0 MOCK - bound to `.mock` here because the backend endpoints this trio
 * calls (`POST /omnichannel/onboarding/webchat/connect`,
 * `GET/PUT /omnichannel/channels/{id}/widget`,
 * `POST /omnichannel/channels/{id}/widget/rotate-secret`) land in plan 34
 * slice S1. Swap the export below to `realWebchatService` in slice S6
 * (AC-WEB-63) - no other call site changes.
 */
import type {
  ConnectWebchatInput,
  ConnectWebchatResult,
  RotateWidgetSecretResult,
  SignOutVisitorsResult,
  UpdateWebchatConfigInput,
  WebchatConfig,
} from '@/types/omnichannel';
import { mockWebchatService } from './webchat-service.mock';

export interface WebchatService {
  /** Provision a new `WEBCHAT` channel (AC-WEB-18). Returns the widget secret
   *  exactly once - the caller must not expect it again from any later read. */
  connect(input: ConnectWebchatInput): Promise<ConnectWebchatResult>;
  /** Read the widget configuration (AC-WEB-03/04). Never carries the secret. */
  getConfig(channelId: string): Promise<WebchatConfig>;
  /** Write-through partial update (appearance, greetings, pre-chat, origins). */
  updateConfig(channelId: string, input: UpdateWebchatConfigInput): Promise<WebchatConfig>;
  /** Mint a fresh secret; the previous one stops verifying immediately. The
   *  token epoch is left unchanged (D-A7B-6). */
  rotateSecret(channelId: string): Promise<RotateWidgetSecretResult>;
  /** Bump the token epoch (sign every live visitor out); the secret is left
   *  unchanged (D-A7B-6). */
  signOutVisitors(channelId: string): Promise<SignOutVisitorsResult>;
}

// S0 MOCK - swap to real in S6 (AC-WEB-63).
export const webchatService: WebchatService = mockWebchatService;
