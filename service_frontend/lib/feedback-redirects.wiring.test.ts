import { describe, expect, it } from 'vitest';
import nextConfig from '../next.config.mjs';
import { FEEDBACK_REDIRECTS } from './feedback-redirects.mjs';

// Guards the wiring: deleting redirects() from next.config must fail a test.
describe('next.config wires the feedback redirects', () => {
  it('serves exactly the FEEDBACK_REDIRECTS rules', async () => {
    expect(nextConfig.redirects).toBeTypeOf('function');
    expect(await nextConfig.redirects!()).toEqual(FEEDBACK_REDIRECTS);
  });
});
