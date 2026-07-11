/** Source + status badge registries + detail path (sprint-4/12). */
import { describe, expect, it } from 'vitest';
import {
  DEVELOPER_LOGS_PATH,
  LOG_SOURCE_REGISTRY,
  LOG_STATUS_REGISTRY,
  integrationLogDetailPath,
} from './log-badges';

describe('integration-log badge registries', () => {
  it('covers every source with a label + tone', () => {
    for (const key of ['inbound_api', 'embed_session', 'outbound_meta', 'webhook_delivery'] as const) {
      expect(LOG_SOURCE_REGISTRY[key].label).toBeTruthy();
      expect(LOG_SOURCE_REGISTRY[key].tone).toBeTruthy();
    }
    expect(LOG_SOURCE_REGISTRY.inbound_api.label).toBe('Inbound API');
    // AC-DLC-24: embed rows get a distinct source badge.
    expect(LOG_SOURCE_REGISTRY.embed_session.label).toBe('Embed');
    expect(LOG_SOURCE_REGISTRY.embed_session.tone).toBe('primary');
  });

  it('covers every status', () => {
    expect(LOG_STATUS_REGISTRY.success.tone).toBe('success');
    expect(LOG_STATUS_REGISTRY.error.tone).toBe('destructive');
    expect(LOG_STATUS_REGISTRY.pending.tone).toBe('warning');
  });

  it('builds a detail path under the console base', () => {
    expect(integrationLogDetailPath('abc')).toBe(`${DEVELOPER_LOGS_PATH}/abc`);
  });
});
