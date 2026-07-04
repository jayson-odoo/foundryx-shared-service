/**
 * Mock avatar service (Phase A) — keeps cropped blobs as data-URLs in memory
 * so every state (upload, replace, remove, slow network, failure) is tunable
 * with no backend running. State is per-session (module scope).
 */
import type { AvatarResult, AvatarService } from './avatar-service';

const LATENCY_MS = 400;

const store = new Map<string, string>(); // 'self' | userId → data-URL

function delay(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, LATENCY_MS));
}

function toDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(new Error('Could not read the image.'));
    reader.readAsDataURL(blob);
  });
}

async function put(key: string, blob: Blob): Promise<AvatarResult> {
  await delay();
  const url = await toDataUrl(blob);
  store.set(key, url);
  return { avatar: url };
}

async function drop(key: string): Promise<AvatarResult> {
  await delay();
  store.delete(key);
  return { avatar: null };
}

export const mockAvatarService: AvatarService = {
  uploadSelf: (blob) => put('self', blob),
  removeSelf: () => drop('self'),
  upload: (userId, blob) => put(userId, blob),
  remove: (userId) => drop(userId),
};
