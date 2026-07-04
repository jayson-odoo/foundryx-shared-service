import { describe, expect, it } from 'vitest';

import { channelProfileSchema } from './channel-schema';
import { mockChannelService } from '@/services/channel-service.mock';
import { WHATSAPP_VERTICALS } from '@/lib/whatsapp-verticals';

describe('channelProfileSchema (validation mirror, plan 06 §6)', () => {
  it('accepts an empty profile (all fields optional)', () => {
    expect(channelProfileSchema.safeParse({}).success).toBe(true);
  });

  it('rejects an invalid email', () => {
    const res = channelProfileSchema.safeParse({ email: 'not-an-email' });
    expect(res.success).toBe(false);
  });

  it('accepts a valid email', () => {
    expect(channelProfileSchema.safeParse({ email: 'hi@example.com' }).success).toBe(true);
  });

  it('rejects a non-http website', () => {
    const res = channelProfileSchema.safeParse({ website1: 'ftp://nope' });
    expect(res.success).toBe(false);
  });

  it('accepts an https website', () => {
    expect(channelProfileSchema.safeParse({ website1: 'https://foundryx.example' }).success).toBe(true);
  });

  it('rejects a vertical outside the Meta enum', () => {
    const res = channelProfileSchema.safeParse({ vertical: 'NOT_A_VERTICAL' });
    expect(res.success).toBe(false);
  });

  it('accepts every Meta vertical', () => {
    for (const v of WHATSAPP_VERTICALS) {
      expect(channelProfileSchema.safeParse({ vertical: v }).success).toBe(true);
    }
  });

  it('has exactly two website fields (cap of 2 is structural — BR-8)', () => {
    const shape = channelProfileSchema.shape;
    expect('website1' in shape).toBe(true);
    expect('website2' in shape).toBe(true);
    expect('website3' in shape).toBe(false);
  });
});

describe('mockChannelService — profile flow', () => {
  it('returns an empty profile before any sync', async () => {
    const p = await mockChannelService.getProfile('chn-001');
    expect(p.about).toBeNull();
    expect(p.profileSyncedAt).toBeNull();
  });

  it('syncProfile mirrors fields + stamps profileSyncedAt', async () => {
    const p = await mockChannelService.syncProfile('chn-002');
    expect(p.about).toBeTruthy();
    expect(p.vertical).toBe('EVENT_PLAN');
    expect(p.profileSyncedAt).not.toBeNull();
    // Persists on the mirror.
    const again = await mockChannelService.getProfile('chn-002');
    expect(again.about).toBe(p.about);
  });

  it('saveProfile writes changed fields + rejects a bad vertical', async () => {
    const saved = await mockChannelService.saveProfile('chn-001', {
      about: 'New about',
      vertical: 'RETAIL',
    });
    expect(saved.about).toBe('New about');
    expect(saved.vertical).toBe('RETAIL');
    await expect(
      mockChannelService.saveProfile('chn-001', { vertical: 'BOGUS' }),
    ).rejects.toThrow();
  });

  it('syncConfig stamps the business account name', async () => {
    const c = await mockChannelService.syncConfig('chn-001');
    expect(c.businessAccountName).toBe('FoundryX Events (dev sandbox)');
    expect(c.lastVerifiedAt).toBeTruthy();
  });
});
