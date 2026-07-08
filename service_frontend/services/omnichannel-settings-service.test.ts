import { beforeEach, describe, expect, it } from 'vitest';
import {
  __resetMockOmnichannelSettings,
  mockOmnichannelSettingsService as svc,
} from './omnichannel-settings-service.mock';

const MB = 1024 * 1024;

beforeEach(() => __resetMockOmnichannelSettings());

describe('mock omnichannel settings service', () => {
  it('returns Meta ceilings with no overrides by default', async () => {
    const s = await svc.get();
    expect(s.workspaceId).toBeNull();
    expect(s.overrides.imageMaxBytes).toBeNull();
    expect(s.effective.IMAGE.ceilingBytes).toBe(5 * MB);
    expect(s.effective.IMAGE.maxBytes).toBe(5 * MB);
    expect(s.effective.IMAGE.acceptedMimes).toContain('image/png');
  });

  it('sets an override and reflects it in effective (clamped to ceiling)', async () => {
    const s = await svc.update({ imageMaxBytes: 2 * MB });
    expect(s.overrides.imageMaxBytes).toBe(2 * MB);
    expect(s.effective.IMAGE.maxBytes).toBe(2 * MB);
  });

  it('clamps an over-ceiling override in effective', async () => {
    const s = await svc.update({ stickerMaxBytes: 5 * MB });
    // stored as sent, but effective is min(configured, ceiling=500KB)
    expect(s.effective.STICKER.maxBytes).toBe(500 * 1024);
  });

  it('clears an override with explicit null', async () => {
    await svc.update({ videoMaxBytes: 8 * MB });
    const s = await svc.update({ videoMaxBytes: null });
    expect(s.overrides.videoMaxBytes).toBeNull();
    expect(s.effective.VIDEO.maxBytes).toBe(16 * MB);
  });

  it('an omitted key keeps the current override', async () => {
    await svc.update({ imageMaxBytes: 1 * MB, videoMaxBytes: 8 * MB });
    const s = await svc.update({ imageMaxBytes: 3 * MB });
    expect(s.overrides.imageMaxBytes).toBe(3 * MB);
    expect(s.overrides.videoMaxBytes).toBe(8 * MB);
  });

  it('VOICE shares the AUDIO editable cap', async () => {
    const s = await svc.update({ audioMaxBytes: 4 * MB });
    expect(s.effective.AUDIO.maxBytes).toBe(4 * MB);
    expect(s.effective.VOICE.maxBytes).toBe(4 * MB);
  });

  it('scopes overrides per workspace independently of the tenant default', async () => {
    await svc.update({ imageMaxBytes: 1 * MB });
    await svc.update({ imageMaxBytes: 2 * MB }, 'wsp-001');
    expect((await svc.get()).overrides.imageMaxBytes).toBe(1 * MB);
    expect((await svc.get('wsp-001')).overrides.imageMaxBytes).toBe(2 * MB);
  });
});
