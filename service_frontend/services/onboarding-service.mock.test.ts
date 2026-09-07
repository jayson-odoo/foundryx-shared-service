/**
 * Mock onboarding service - Messenger + Instagram connect flow (plan 32 / A7a,
 * S0 MOCK). Mirrors the real connect-flow contract the backend implements in
 * S3: `/meta/pages` then `/meta/connect`, an already-connected page/account
 * never offered, and a page uniqueness violation refused.
 */
import { describe, expect, it } from 'vitest';
import { mockOnboardingService } from './onboarding-service.mock';

describe('mockOnboardingService.listMetaPages', () => {
  it('excludes a page already bound to a live channel (AC-CHN-02)', async () => {
    const { pages } = await mockOnboardingService.listMetaPages({ channelType: 'FACEBOOK', code: 'code' });
    const connectedIds = pages.filter((p) => p.connected).map((p) => p.id);
    expect(connectedIds).toContain('pg-701'); // seeded chn-fb-001
    const offered = pages.filter((p) => !p.connected).map((p) => p.id);
    expect(offered).not.toContain('pg-701');
  });

  it('only offers pages whose linked Instagram account is present (D-A7-14/44)', async () => {
    const { pages } = await mockOnboardingService.listMetaPages({ channelType: 'INSTAGRAM', code: 'code' });
    expect(pages.every((p) => !!p.igAccountId)).toBe(true);
  });

  it('returns a short-lived single-use session id', async () => {
    const a = await mockOnboardingService.listMetaPages({ channelType: 'FACEBOOK', code: 'code' });
    const b = await mockOnboardingService.listMetaPages({ channelType: 'FACEBOOK', code: 'code' });
    expect(a.sessionId).not.toEqual(b.sessionId);
    expect(Date.parse(a.expiresAt)).toBeGreaterThan(Date.now());
  });
});

describe('mockOnboardingService.connectMetaChannel', () => {
  it('rejects an already-connected page/account (mirrors the S3 409)', async () => {
    await expect(
      mockOnboardingService.connectMetaChannel({
        sessionId: 'sandbox',
        workspaceId: 'wsp-001',
        channelType: 'FACEBOOK',
        pageId: 'pg-701',
      }),
    ).rejects.toThrow(/already connected/);
  });

  it('provisions a channel for an available page', async () => {
    const channel = await mockOnboardingService.connectMetaChannel({
      sessionId: 'sandbox',
      workspaceId: 'wsp-001',
      channelType: 'FACEBOOK',
      pageId: 'pg-703',
    });
    expect(channel.channelType).toBe('FACEBOOK');
    expect(channel.externalAccountId).toBe('pg-703');
  });
});
