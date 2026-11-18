/**
 * Lead Capture TEST CONSUMER (hand tests only, plan 64 L-C). A stand-in for a
 * product's "Connect a source" button: its server routes hold a gateway key
 * and mint connect sessions / pull leads like a real consumer's backend.
 *
 * NEVER in production: everything is off unless BOTH server env values are
 * set on the test copy (production deploys set neither; a vitest pins that
 * `deploy.yml` and `docker-compose.yml` never mention them):
 * - `LEAD_CAPTURE_TEST_CONSUMER=on`
 * - `LEAD_CAPTURE_TEST_CONSUMER_KEY=fxl_live_...` (a key whose allowed
 *   origins list this copy's frontend origin)
 * Server-only: never import this from a client component.
 */
export interface TestConsumerConfig {
  key: string;
  backend: string;
}

export function testConsumerConfig(env: Record<string, string | undefined> = process.env): TestConsumerConfig | null {
  const key = (env.LEAD_CAPTURE_TEST_CONSUMER_KEY ?? '').trim();
  if (env.LEAD_CAPTURE_TEST_CONSUMER !== 'on' || !key.startsWith('fxl_live_')) return null;
  const backend = (env.BACKEND_API_URL ?? env.NEXT_PUBLIC_BACKEND_API_URL ?? 'http://localhost:8001').replace(/\/$/, '');
  return { key, backend };
}

/** The page's own origin from the request, or null when a POST came from
 * another site (only this page may mint sessions with the key). */
export function sameOriginOf(headers: Headers, requestUrl: string): string | null {
  const own = new URL(requestUrl).origin;
  const host = headers.get('host');
  const proto = headers.get('x-forwarded-proto') ?? new URL(requestUrl).protocol.replace(':', '');
  const pageOrigin = host ? `${proto}://${host}` : own;
  const sent = headers.get('origin');
  if (sent && sent !== pageOrigin) return null;
  return pageOrigin;
}
