import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { sameOriginOf, testConsumerConfig } from './lead-capture-test-consumer';

const root = path.join(__dirname, '..', '..');

describe('lead capture test consumer guard', () => {
  it('is off unless both values are set', () => {
    expect(testConsumerConfig({})).toBeNull();
    expect(testConsumerConfig({ LEAD_CAPTURE_TEST_CONSUMER: 'on' })).toBeNull();
    expect(testConsumerConfig({ LEAD_CAPTURE_TEST_CONSUMER_KEY: 'fxl_live_x' })).toBeNull();
    expect(testConsumerConfig({ LEAD_CAPTURE_TEST_CONSUMER: 'on', LEAD_CAPTURE_TEST_CONSUMER_KEY: 'not-a-key' })).toBeNull();
    expect(
      testConsumerConfig({
        LEAD_CAPTURE_TEST_CONSUMER: 'on',
        LEAD_CAPTURE_TEST_CONSUMER_KEY: 'fxl_live_x',
        BACKEND_API_URL: 'http://be:8109/',
      }),
    ).toEqual({ key: 'fxl_live_x', backend: 'http://be:8109' });
  });

  it('is never configured by the production deploy', () => {
    for (const file of ['.github/workflows/deploy.yml', 'docker-compose.yml']) {
      expect(fs.readFileSync(path.join(root, file), 'utf8')).not.toMatch(/LEAD_CAPTURE_TEST_CONSUMER/);
    }
  });

  it('mints only for a same-origin caller', () => {
    const h = (o: Record<string, string>) => new Headers(o);
    expect(sameOriginOf(h({ host: '100.127.79.93:3109', origin: 'http://100.127.79.93:3109' }), 'http://100.127.79.93:3109/api/x')).toBe(
      'http://100.127.79.93:3109',
    );
    expect(sameOriginOf(h({ host: '100.127.79.93:3109', origin: 'https://evil.example' }), 'http://100.127.79.93:3109/api/x')).toBeNull();
  });
});
