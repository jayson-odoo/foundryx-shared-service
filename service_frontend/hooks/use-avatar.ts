'use client';

import { useMemo, useState } from 'react';
import { useSession } from 'next-auth/react';
import { avatarService } from '@/services/avatar-service';

export interface OwnAvatarApi {
  /** Display URL — freshest known value (local result wins over the session). */
  avatar: string | null;
  upload: (blob: Blob) => Promise<void>;
  remove: () => Promise<void>;
}

// Survives component remounts: update() flips useSession to 'loading', the
// protected layout swaps to its loader and the page REMOUNTS (plan 04 lesson)
// — a useState-only override would die right after every upload.
let ownAvatarOverride: string | null | undefined;

/**
 * Self-service avatar (plan 06 D5, /account). After a change, NextAuth
 * `update()` re-pulls /auth/me into the session (header + everywhere reading
 * `session.user.avatar` follow). The local override bridges the gap until the
 * session catches up — and carries the whole display in Phase A, where the
 * mock backend isn't behind /auth/me.
 */
export function useOwnAvatar(): OwnAvatarApi {
  const { data: session, update } = useSession();
  const [override, setOverride] = useState<string | null | undefined>(ownAvatarOverride);

  const apply = (value: string | null) => {
    ownAvatarOverride = value;
    setOverride(value);
  };

  const upload = async (blob: Blob) => {
    const result = await avatarService.uploadSelf(blob);
    apply(result.avatar);
    await update();
  };

  const remove = async () => {
    await avatarService.removeSelf();
    apply(null);
    await update();
  };

  return {
    avatar: override !== undefined ? override : (session?.user.avatar ?? null),
    upload,
    remove,
  };
}

export interface UserAvatarApi {
  upload: (blob: Blob) => Promise<string | null>;
  remove: () => Promise<null>;
}

/**
 * Admin path (user form, users.update) — returns the fresh URL so the caller
 * can patch its local record state; no session involvement (it's someone
 * else's avatar).
 */
export function useUserAvatar(userId: string): UserAvatarApi {
  // Stable identity — callers hold this in useMemo deps (user form config).
  return useMemo(
    () => ({
      upload: async (blob: Blob) => (await avatarService.upload(userId, blob)).avatar,
      remove: async () => {
        await avatarService.remove(userId);
        return null;
      },
    }),
    [userId],
  );
}
