/**
 * Avatar service (plan sprint-2/06 D5) - the boundary the avatar surfaces talk
 * to (via hooks). Phase A binds the mock; Phase B swaps `avatarService` to the
 * real api-client impl in ONE line (bottom of file). The interface IS the
 * backend contract:
 *
 * - self  → POST/DELETE `/me/avatar` (perm-free self-scope, like /me/preferences)
 * - admin → POST/DELETE `/users/{id}/avatar` (rides users.update)
 *
 * Uploads carry the CROPPED blob (client downscales to 512px, lib/image-crop);
 * the response returns the fresh display URL (key resolved server-side - DB
 * stores storage keys, never URLs, D4).
 */
import { realAvatarService } from './avatar-service.real';

export interface AvatarResult {
  /** Fresh display URL (`?v=` cache-busted), or null after a remove. */
  avatar: string | null;
}

export interface AvatarService {
  /** Set the signed-in user's own avatar. */
  uploadSelf(blob: Blob): Promise<AvatarResult>;
  removeSelf(): Promise<AvatarResult>;
  /** Admin path - set another user's avatar (users.update). */
  upload(userId: string, blob: Blob): Promise<AvatarResult>;
  remove(userId: string): Promise<AvatarResult>;
}

// Phase B swap done - mock retained in avatar-service.mock.ts for tests.
export const avatarService: AvatarService = realAvatarService;
