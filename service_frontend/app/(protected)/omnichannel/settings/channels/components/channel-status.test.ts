/**
 * Channel type/status registries (plan 32 / A7a, AC-CHN-04) - the channels
 * list "Type" column badge + label source parity-pinned to
 * `lib/channel-capabilities.ts`.
 */
import { describe, expect, it } from 'vitest';
import { CHANNEL_CAPABILITIES } from '@/lib/channel-capabilities';
import { CHANNEL_TYPE_LABELS, CHANNEL_TYPE_REGISTRY } from './channel-status';

describe('CHANNEL_TYPE_LABELS / CHANNEL_TYPE_REGISTRY', () => {
  it('declares exactly the three implemented types, matching the capability record', () => {
    expect(Object.keys(CHANNEL_TYPE_LABELS).sort()).toEqual(['FACEBOOK', 'INSTAGRAM', 'WHATSAPP']);
    expect(Object.keys(CHANNEL_TYPE_REGISTRY).sort()).toEqual(['FACEBOOK', 'INSTAGRAM', 'WHATSAPP']);
  });

  it('labels mirror lib/channel-capabilities.ts (one source of truth)', () => {
    expect(CHANNEL_TYPE_LABELS.WHATSAPP).toBe(CHANNEL_CAPABILITIES.WHATSAPP.label);
    expect(CHANNEL_TYPE_LABELS.FACEBOOK).toBe(CHANNEL_CAPABILITIES.FACEBOOK.label);
    expect(CHANNEL_TYPE_LABELS.INSTAGRAM).toBe(CHANNEL_CAPABILITIES.INSTAGRAM.label);
  });

  it('each type gets its own registry tone (distinct from the connection-status pill)', () => {
    const tones = new Set(Object.values(CHANNEL_TYPE_REGISTRY).map((m) => m.tone));
    expect(tones.size).toBe(3);
  });
});
