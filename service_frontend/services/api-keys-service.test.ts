import { describe, expect, it, beforeEach } from 'vitest';
import { mockApiKeysService, __resetApiKeysMock } from './api-keys-service.mock';
import type { ApiKeyItem } from '@/types/api-keys';

const WS = 'wsp-001';

beforeEach(() => {
  __resetApiKeysMock();
});

describe('api-keys service mock (omnichannel Slice 3)', () => {
  it('mints a key and returns the full plaintext ONCE', async () => {
    const result = await mockApiKeysService.mint(WS, 'Production');
    expect(result.fullKey).toMatch(/^fxw_live_/);
    // The full key is longer than its masked form (carries the secret tail).
    expect(result.fullKey.length).toBeGreaterThan(result.key.maskedKey.length);
    expect(result.key.name).toBe('Production');
    expect(result.key.status).toBe('ACTIVE');
    expect(result.key.workspaceId).toBe(WS);
  });

  it('the masked key follows the fxw_live_{prefix}•••• format and hides the secret', async () => {
    const { key, fullKey } = await mockApiKeysService.mint(WS, 'CI');
    expect(key.maskedKey).toBe(`fxw_live_${key.keyPrefix}••••`);
    expect(key.maskedKey).toContain('••••');
    // The masked form never contains the full secret.
    expect(key.maskedKey).not.toBe(fullKey);
    expect(fullKey.startsWith(`fxw_live_${key.keyPrefix}`)).toBe(true);
  });

  it('list never carries the full plaintext key', async () => {
    await mockApiKeysService.mint(WS, 'One');
    await mockApiKeysService.mint(WS, 'Two');
    const rows = await mockApiKeysService.list(WS);
    expect(rows).toHaveLength(2);
    for (const row of rows) {
      // ApiKeyItem shape has no fullKey field at all.
      expect((row as ApiKeyItem & { fullKey?: string }).fullKey).toBeUndefined();
      expect(row.maskedKey).toContain('••••');
    }
  });

  it('lists newest-first', async () => {
    const a = await mockApiKeysService.mint(WS, 'First');
    // ensure a distinct createdAt ordering
    await new Promise((r) => setTimeout(r, 5));
    const b = await mockApiKeysService.mint(WS, 'Second');
    const rows = await mockApiKeysService.list(WS);
    expect(rows[0].id).toBe(b.key.id);
    expect(rows[1].id).toBe(a.key.id);
  });

  it('revoke stamps REVOKED + revokedAt and is scoped to the workspace', async () => {
    const { key } = await mockApiKeysService.mint(WS, 'Temp');
    const revoked = await mockApiKeysService.revoke(WS, key.id);
    expect(revoked.status).toBe('REVOKED');
    expect(revoked.revokedAt).not.toBeNull();
    const rows = await mockApiKeysService.list(WS);
    expect(rows.find((r) => r.id === key.id)?.status).toBe('REVOKED');
  });

  it('revoke of an unknown key rejects', async () => {
    await expect(mockApiKeysService.revoke(WS, 'nope')).rejects.toThrow();
  });

  it('scopes keys per workspace', async () => {
    await mockApiKeysService.mint('wsp-A', 'A');
    const other = await mockApiKeysService.list('wsp-B');
    expect(other).toHaveLength(0);
  });
});
