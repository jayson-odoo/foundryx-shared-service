import { describe, expect, it } from 'vitest';
import { broadcastAudienceSchema, broadcastFormSchema, templateBindingSchema } from './broadcast-schema';

const BASE = {
  name: 'Weekend promo',
  labels: [] as string[],
  channelId: 'chn-1',
  templateId: 'tpl-1',
  bindings: { header: [], body: [], buttons: [] },
  scheduleMode: 'now' as const,
  scheduledAt: null as string | null,
};

describe('broadcastAudienceSchema - exactly one source', () => {
  it('accepts a segment-only audience', () => {
    expect(broadcastAudienceSchema.safeParse({ kind: 'segment', segmentId: 'seg-1' }).success).toBe(true);
  });

  it('accepts a filter-only audience', () => {
    expect(
      broadcastAudienceSchema.safeParse({
        kind: 'filter',
        filter: { kind: 'group', combinator: 'and', rules: [{ kind: 'condition', field: 'priority', operator: 'eq', value: 'HIGH' }] },
      }).success,
    ).toBe(true);
  });

  it('accepts an explicit contacts audience', () => {
    expect(broadcastAudienceSchema.safeParse({ kind: 'contacts', contactIds: ['cnt-1'] }).success).toBe(true);
  });

  it('rejects a segment audience with no segmentId chosen', () => {
    const result = broadcastAudienceSchema.safeParse({ kind: 'segment' });
    expect(result.success).toBe(false);
  });

  it('rejects an audience carrying MORE than one source at once', () => {
    const result = broadcastAudienceSchema.safeParse({
      kind: 'segment',
      segmentId: 'seg-1',
      contactIds: ['cnt-1'],
    });
    expect(result.success).toBe(false);
  });

  it('rejects a filter audience with zero conditions', () => {
    const result = broadcastAudienceSchema.safeParse({
      kind: 'filter',
      filter: { kind: 'group', combinator: 'and', rules: [] },
    });
    expect(result.success).toBe(false);
  });

  // Plan 29 S4 real-data wiring bug: `BroadcastAudienceOut` (the real
  // backend response) always emits all four keys - the three UNUSED
  // branches are `null`, never an absent key like the S0 mock produced.
  // Loading a real saved broadcast back into the builder must not fail
  // closed on "Expected string, received null".
  it('accepts a real-wire contacts audience where segmentId/segmentName/filter are explicit null', () => {
    const result = broadcastAudienceSchema.safeParse({
      kind: 'contacts',
      segmentId: null,
      segmentName: null,
      filter: null,
      contactIds: ['cnt-1', 'cnt-2'],
    });
    expect(result.success).toBe(true);
  });

  it('accepts a real-wire segment audience where filter/contactIds are explicit null', () => {
    const result = broadcastAudienceSchema.safeParse({
      kind: 'segment',
      segmentId: 'seg-1',
      segmentName: 'VIP',
      filter: null,
      contactIds: null,
    });
    expect(result.success).toBe(true);
  });
});

describe('templateBindingSchema', () => {
  it('accepts a static binding with plain text', () => {
    expect(templateBindingSchema.safeParse({ source: 'static', text: 'Thanks for shopping!' }).success).toBe(true);
  });

  it('rejects a static binding carrying template token syntax (anti-SSTI guard)', () => {
    const result = templateBindingSchema.safeParse({ source: 'static', text: 'Hi {{1}}' });
    expect(result.success).toBe(false);
  });

  // Review round 1, S3: an empty static binding used to save cleanly, then
  // resolve to a skipped recipient at send time for EVERY recipient
  // (silently "Sent" with 0 sends) - reject it at save on both layers.
  it('rejects a static binding with empty text', () => {
    const result = templateBindingSchema.safeParse({ source: 'static', text: '' });
    expect(result.success).toBe(false);
  });

  it('rejects a static binding with whitespace-only text', () => {
    const result = templateBindingSchema.safeParse({ source: 'static', text: '   ' });
    expect(result.success).toBe(false);
  });

  it('accepts a contactField binding with a non-empty fallback', () => {
    expect(
      templateBindingSchema.safeParse({ source: 'contactField', field: 'firstName', fallback: 'there' }).success,
    ).toBe(true);
  });

  it('rejects a contactField binding with an empty fallback', () => {
    const result = templateBindingSchema.safeParse({ source: 'contactField', field: 'firstName', fallback: '' });
    expect(result.success).toBe(false);
  });

  it('rejects a contactField binding with no field chosen', () => {
    const result = templateBindingSchema.safeParse({ source: 'contactField', field: '', fallback: 'there' });
    expect(result.success).toBe(false);
  });
});

describe('broadcastFormSchema', () => {
  const validAudience = { kind: 'segment' as const, segmentId: 'seg-1' };

  it('accepts a fully valid Send-now draft', () => {
    const result = broadcastFormSchema.safeParse({ ...BASE, audience: validAudience });
    expect(result.success).toBe(true);
  });

  it('rejects an empty name', () => {
    const result = broadcastFormSchema.safeParse({ ...BASE, name: '', audience: validAudience });
    expect(result.success).toBe(false);
  });

  it('rejects a name over 200 characters', () => {
    const result = broadcastFormSchema.safeParse({ ...BASE, name: 'x'.repeat(201), audience: validAudience });
    expect(result.success).toBe(false);
  });

  it('rejects scheduleMode "schedule" with no scheduledAt', () => {
    const result = broadcastFormSchema.safeParse({
      ...BASE,
      audience: validAudience,
      scheduleMode: 'schedule',
      scheduledAt: null,
    });
    expect(result.success).toBe(false);
  });

  it('rejects a scheduledAt in the past', () => {
    const result = broadcastFormSchema.safeParse({
      ...BASE,
      audience: validAudience,
      scheduleMode: 'schedule',
      scheduledAt: new Date(Date.now() - 60_000).toISOString(),
    });
    expect(result.success).toBe(false);
  });

  it('accepts a scheduledAt in the future', () => {
    const result = broadcastFormSchema.safeParse({
      ...BASE,
      audience: validAudience,
      scheduleMode: 'schedule',
      scheduledAt: new Date(Date.now() + 3_600_000).toISOString(),
    });
    expect(result.success).toBe(true);
  });

  it('rejects a broadcast with no channel chosen', () => {
    const result = broadcastFormSchema.safeParse({ ...BASE, channelId: '', audience: validAudience });
    expect(result.success).toBe(false);
  });

  it('rejects a broadcast with no template chosen', () => {
    const result = broadcastFormSchema.safeParse({ ...BASE, templateId: '', audience: validAudience });
    expect(result.success).toBe(false);
  });

  it("derives the binding count from the template shape (as many rows as bindings provided)", () => {
    const result = broadcastFormSchema.safeParse({
      ...BASE,
      audience: validAudience,
      bindings: {
        header: [{ source: 'contactField', field: 'firstName', fallback: 'there' }],
        body: [
          { source: 'contactField', field: 'firstName', fallback: 'there' },
          { source: 'static', text: 'order #1234' },
        ],
        buttons: [],
      },
    });
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.bindings.header).toHaveLength(1);
      expect(result.data.bindings.body).toHaveLength(2);
    }
  });
});
