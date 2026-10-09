import { describe, expect, it } from 'vitest';
import { mockWebchatService } from './webchat-service.mock';

/**
 * Mock web chat admin service (plan 34 / A7b, S0 MOCK - AC-WEB-06/10/18).
 */
describe('mockWebchatService', () => {
  it('getConfig() reads the seeded dev channel with no secret field anywhere on it', async () => {
    const config = await mockWebchatService.getConfig('chn-web-001');
    expect(config.widgetKey).toBe('wk_demo0000000000000000000001');
    expect(config.allowedOrigins).toContain('http://localhost:3012');
    expect(config).not.toHaveProperty('widgetSecret');
  });

  it('connect() provisions a channel + config and reveals the secret exactly once', async () => {
    const result = await mockWebchatService.connect({
      name: 'Support widget',
      workspaceId: 'wsp-001',
      allowedOrigins: ['https://shop.acme.test'],
    });
    expect(result.channelType).toBe('WEBCHAT');
    expect(result.widgetKey).toBeTruthy();
    expect(result.widgetSecret).toBeTruthy();

    const config = await mockWebchatService.getConfig(result.id);
    expect(config.allowedOrigins).toEqual(['https://shop.acme.test']);
    expect(config).not.toHaveProperty('widgetSecret');
  });

  it('updateConfig() merges a partial input, leaving other fields untouched', async () => {
    const before = await mockWebchatService.getConfig('chn-web-001');
    const after = await mockWebchatService.updateConfig('chn-web-001', {
      greeting: 'Welcome back!',
    });
    expect(after.greeting).toBe('Welcome back!');
    expect(after.appearance).toEqual(before.appearance);
    expect(after.offlineGreeting).toBe(before.offlineGreeting);
  });

  it('rotateSecret() mints a fresh secret and never echoes it from getConfig()', async () => {
    const { widgetSecret } = await mockWebchatService.rotateSecret('chn-web-001');
    expect(widgetSecret).toBeTruthy();
    const config = await mockWebchatService.getConfig('chn-web-001');
    expect(config).not.toHaveProperty('widgetSecret');
  });

  it('rotateSecret() leaves the token epoch unchanged (D-A7B-6)', async () => {
    const before = await mockWebchatService.getConfig('chn-web-001');
    await mockWebchatService.rotateSecret('chn-web-001');
    const after = await mockWebchatService.getConfig('chn-web-001');
    expect(after.tokenEpoch).toBe(before.tokenEpoch);
  });

  it('signOutVisitors() bumps the token epoch without touching the secret path', async () => {
    const before = await mockWebchatService.getConfig('chn-web-001');
    const { tokenEpoch } = await mockWebchatService.signOutVisitors('chn-web-001');
    expect(tokenEpoch).toBe(before.tokenEpoch + 1);
  });
});
