import { beforeEach, describe, expect, it } from 'vitest';
import {
  __resetMockEmbedConfig,
  mockEmbedConfigService,
} from './embed-config-service.mock';

beforeEach(() => __resetMockEmbedConfig());

describe('mockEmbedConfigService', () => {
  it('starts empty (not enabled, no secret)', async () => {
    const cfg = await mockEmbedConfigService.get();
    expect(cfg.connectionId).toBeNull();
    expect(cfg.hasSecret).toBe(false);
    expect(cfg.allowedOrigins).toEqual([]);
    expect(cfg.workspaces.length).toBeGreaterThan(0);
  });

  it('enable is idempotent', async () => {
    const a = await mockEmbedConfigService.enable();
    const b = await mockEmbedConfigService.enable();
    expect(a.connectionId).toBeTruthy();
    expect(b.connectionId).toBe(a.connectionId);
  });

  it('rotate returns a secret (different each time) and flips hasSecret', async () => {
    await mockEmbedConfigService.enable();
    const first = await mockEmbedConfigService.rotateSecret();
    const second = await mockEmbedConfigService.rotateSecret();
    expect(first.embedSecret).toBeTruthy();
    expect(second.embedSecret).not.toBe(first.embedSecret);
    expect((await mockEmbedConfigService.get()).hasSecret).toBe(true);
  });

  it('rotate before enable throws', async () => {
    await expect(mockEmbedConfigService.rotateSecret()).rejects.toThrow();
  });

  it('setOrigins validates, normalizes and dedupes', async () => {
    await mockEmbedConfigService.enable();
    const cfg = await mockEmbedConfigService.setOrigins([
      'https://crm.acme.com',
      'http://localhost:3000',
      'https://crm.acme.com',
    ]);
    expect(cfg.allowedOrigins).toEqual(['https://crm.acme.com', 'http://localhost:3000']);
  });

  it('setOrigins rejects a path / trailing slash / non-localhost http', async () => {
    await mockEmbedConfigService.enable();
    await expect(mockEmbedConfigService.setOrigins(['https://crm.acme.com/leads'])).rejects.toThrow();
    await expect(mockEmbedConfigService.setOrigins(['https://crm.acme.com/'])).rejects.toThrow();
    await expect(mockEmbedConfigService.setOrigins(['http://crm.acme.com'])).rejects.toThrow();
  });
});
