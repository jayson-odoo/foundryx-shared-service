/**
 * Web chat channel service (admin side, plan 34 / A7b). Provisions a
 * `WEBCHAT` channel, reads/writes its widget configuration, and rotates its
 * signing secret. Mirrors `channel-service.ts`'s trio shape (`.mock`/`.real`,
 * one boundary swap).
 *
 * Plan 34 / A7b, S6 (AC-WEB-63) - bound to `realWebchatService` below, the
 * one service-boundary swap `mockWebchatService` served during S0/S4/S5.
 */
import type {
  ConnectWebchatInput,
  ConnectWebchatResult,
  RotateWidgetSecretResult,
  SignOutVisitorsResult,
  UpdateWebchatConfigInput,
  WebchatConfig,
} from '@/types/omnichannel';
import { realWebchatService } from './webchat-service.real';

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

export const webchatService: WebchatService = realWebchatService;
