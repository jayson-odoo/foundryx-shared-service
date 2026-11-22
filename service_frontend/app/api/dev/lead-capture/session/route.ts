/**
 * TEST CONSUMER: mint a connect session with the test key (server side; the
 * key never reaches the browser). 404 unless the test consumer is switched
 * on (`lib/lead-capture-test-consumer.ts`).
 */
import { NextResponse } from 'next/server';
import { sameOriginOf, testConsumerConfig } from '@/lib/lead-capture-test-consumer';

export const dynamic = 'force-dynamic';

export async function POST(req: Request) {
  const config = testConsumerConfig();
  if (!config) return new NextResponse('Not found', { status: 404 });
  const origin = sameOriginOf(req.headers, req.url);
  if (!origin) return NextResponse.json({ error: { message: 'Wrong origin.' } }, { status: 403 });
  let sourceId: string | null = null;
  try {
    const body = (await req.json()) as { sourceId?: unknown };
    sourceId = typeof body.sourceId === 'string' && body.sourceId ? body.sourceId : null;
  } catch {
    sourceId = null;
  }
  const res = await fetch(`${config.backend}/api/v1/lead-capture/connect-sessions`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${config.key}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ returnOrigin: origin, sourceId }),
    cache: 'no-store',
  });
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}
