/**
 * Channel service — boundary the UI talks to. Phase A binds the MOCK; Phase B
 * swaps `channelService` to the real api-client impl in ONE line (bottom).
 *
 * Note: channels are CREATED via the Embedded Signup onboarding flow (see
 * onboarding-service), not a create form — so there is no `create` here.
 */
import type {
  Channel,
  ChannelProfile,
  UpdateChannelInput,
  UpdateChannelProfileInput,
} from '@/types/omnichannel';
import type { ListQuery, ListResult } from '@/types/resource';
import { realChannelService } from './channel-service.real';

export interface TestConnectionResult {
  ok: boolean;
  message: string;
  checkedAt: string; // ISO
}

export interface ChannelService {
  list(query: ListQuery): Promise<ListResult<Channel>>;
  get(id: string): Promise<Channel>;
  getAt(query: ListQuery, index: number): Promise<{ channel: Channel | null; total: number }>;
  /** Channels attached to a given workspace (for the workspace's Channels tab). */
  listByWorkspace(workspaceId: string): Promise<Channel[]>;
  update(id: string, input: UpdateChannelInput): Promise<Channel>;
  /** Lightweight ping to Meta to re-verify the number (plan 04 §5.2 step 5). */
  testConnection(id: string): Promise<TestConnectionResult>;
  /** Pull live WABA + phone identity from Meta into the local mirror (plan 06). */
  syncConfig(id: string): Promise<Channel>;
  /** Read the mirrored WhatsApp Business Profile (no Meta call — instant). */
  getProfile(id: string): Promise<ChannelProfile>;
  /** Pull the latest profile from Meta into the local mirror. */
  syncProfile(id: string): Promise<ChannelProfile>;
  /** Write-through: validate + POST changed fields to Meta, refresh local. */
  saveProfile(id: string, input: UpdateChannelProfileInput): Promise<ChannelProfile>;
  /** Disconnect (soft-trash) a channel. */
  disconnect(ids: string[]): Promise<void>;
  /** Restore trashed channels back to the active view. */
  restore(ids: string[]): Promise<void>;
  /** Permanently delete trashed channels. */
  remove(ids: string[]): Promise<void>;
  exportCsv(query: ListQuery, columns: string[], ids?: string[]): Promise<string>;
}

// Phase B: real api-client implementation. (Mock retained in *.mock.ts.)
export const channelService: ChannelService = realChannelService;
