import { describe, expect, it } from 'vitest';
import {
  WEBHOOK_STATUS_REGISTRY,
  WEBHOOK_DELIVERY_STATUS_REGISTRY,
  WEBHOOK_EVENT_LABELS,
  WEBHOOK_EVENT_OPTIONS,
  eventLabel,
} from './webhook-status';

describe('webhook status registries (omnichannel Slice 4)', () => {
  it('maps every endpoint status to the expected tone', () => {
    expect(WEBHOOK_STATUS_REGISTRY.ACTIVE.tone).toBe('success');
    expect(WEBHOOK_STATUS_REGISTRY.DISABLED.tone).toBe('secondary');
    expect(WEBHOOK_STATUS_REGISTRY.AUTO_DISABLED.tone).toBe('destructive');
  });

  it('maps every delivery status to the expected tone', () => {
    expect(WEBHOOK_DELIVERY_STATUS_REGISTRY.SUCCESS.tone).toBe('success');
    expect(WEBHOOK_DELIVERY_STATUS_REGISTRY.PENDING.tone).toBe('warning');
    expect(WEBHOOK_DELIVERY_STATUS_REGISTRY.FAILED.tone).toBe('destructive');
  });
});

describe('webhook event-type labels', () => {
  it('maps each event type to its friendly label', () => {
    expect(WEBHOOK_EVENT_LABELS['message.inbound']).toBe('Inbound messages');
    expect(WEBHOOK_EVENT_LABELS['message.status']).toBe('Delivery receipts');
    expect(WEBHOOK_EVENT_LABELS['contact.updated']).toBe('Contact updates');
    expect(WEBHOOK_EVENT_LABELS['message.reaction']).toBe('Reactions');
  });

  it('exposes the four events as picker options in label/value shape', () => {
    expect(WEBHOOK_EVENT_OPTIONS).toHaveLength(4);
    expect(WEBHOOK_EVENT_OPTIONS.map((o) => o.value)).toEqual([
      'message.inbound',
      'message.status',
      'contact.updated',
      'message.reaction',
    ]);
  });

  it('eventLabel degrades unknown keys to the raw value', () => {
    expect(eventLabel('message.inbound')).toBe('Inbound messages');
    expect(eventLabel('some.future.event')).toBe('some.future.event');
  });
});
