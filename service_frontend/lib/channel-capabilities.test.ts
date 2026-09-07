import { describe, expect, it } from 'vitest';
import { CHANNEL_CAPABILITIES, CHANNEL_TYPES, channelCapabilities } from './channel-capabilities';

/**
 * Golden capability table test (plan 32 / A7a §5.5, AC-CHN-06/61). Pins the
 * frontend UX mirror; once `messaging_policy.CAPABILITIES` lands (S2) a
 * backend test pins the same table from its side (D-A7-10).
 */
describe('CHANNEL_CAPABILITIES', () => {
  it('declares exactly the three implemented channel types', () => {
    expect(Object.keys(CHANNEL_CAPABILITIES).sort()).toEqual(['FACEBOOK', 'INSTAGRAM', 'WHATSAPP']);
    expect(CHANNEL_TYPES).toEqual(['WHATSAPP', 'FACEBOOK', 'INSTAGRAM']);
  });

  it('WhatsApp: template re-engagement, no human-agent extension, every media kind', () => {
    const c = channelCapabilities('WHATSAPP');
    expect(c.reengageMode).toBe('template');
    expect(c.humanAgentHours).toBeNull();
    expect(c.template).toBe(true);
    expect(c.list).toBe(true);
    expect(c.location).toBe(true);
    expect(c.contacts).toBe(true);
    expect(c.outboundReaction).toBe(true);
    expect(c.media).toEqual({ image: true, video: true, audio: true, voice: true, document: true, sticker: true });
  });

  it('Messenger: human-agent re-engagement, quick replies, no templates/list/location/contacts', () => {
    const c = channelCapabilities('FACEBOOK');
    expect(c.reengageMode).toBe('human_agent');
    expect(c.humanAgentHours).toBe(168);
    expect(c.quickReplies).toBe(true);
    expect(c.template).toBe(false);
    expect(c.list).toBe(false);
    expect(c.location).toBe(false);
    expect(c.contacts).toBe(false);
    expect(c.outboundReaction).toBe(false);
    expect(c.media.document).toBe(true);
    expect(c.media.sticker).toBe(false);
  });

  it('Instagram: same policy shape as Messenger except no document attachments', () => {
    const fb = channelCapabilities('FACEBOOK');
    const ig = channelCapabilities('INSTAGRAM');
    expect(ig.reengageMode).toBe(fb.reengageMode);
    expect(ig.humanAgentHours).toBe(fb.humanAgentHours);
    expect(ig.quickReplies).toBe(fb.quickReplies);
    expect(ig.media.document).toBe(false);
    expect(ig.media).not.toEqual(fb.media);
  });

  it('every type declares a 24h standard window', () => {
    for (const type of CHANNEL_TYPES) {
      expect(channelCapabilities(type).windowHours).toBe(24);
    }
  });

  it('an unmodelled channel type (no DB enum, BL-SS-122) falls back to a neutral UNKNOWN record instead of throwing', () => {
    expect(() => channelCapabilities('TELEGRAM')).not.toThrow();
    const c = channelCapabilities('TELEGRAM');
    expect(c.icon).toBeDefined();
    expect(c.reengageMode).toBe('none');
    expect(c.template).toBe(false);
    expect(c.quickReplies).toBe(false);
    expect(c.media).toEqual({ image: false, video: false, audio: false, voice: false, document: false, sticker: false });
  });
});
