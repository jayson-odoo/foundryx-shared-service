import { describe, expect, it } from 'vitest';
import { nextDeliveryMode } from './delivery-mode';

describe('nextDeliveryMode', () => {
  it('the first load follows the stored state', () => {
    expect(nextDeliveryMode(null, null, 2)).toBe('push');
    expect(nextDeliveryMode(null, null, 0)).toBe('pull');
  });

  it('removing the last receiver (from any menu) switches to Pull only', () => {
    // Crew pass 041306ae: after the right-click Remove of the last receiver the
    // page stayed on Push with an empty list until a reload.
    expect(nextDeliveryMode('push', 1, 0)).toBe('pull');
  });

  it('keeps a Push chosen by hand while the first receiver is being added', () => {
    expect(nextDeliveryMode('push', 0, 0)).toBe('push');
    expect(nextDeliveryMode('push', 0, 1)).toBe('push');
    expect(nextDeliveryMode('push', 3, 2)).toBe('push');
  });
});
