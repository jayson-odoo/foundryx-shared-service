/**
 * TEST CONSUMER: the key's sources and its newest leads (pull API, as a
 * product's backend reads them). 404 unless the test consumer is on.
 */
import { NextResponse } from 'next/server';
import { testConsumerConfig } from '@/lib/lead-capture-test-consumer';

export const dynamic = 'force-dynamic';

const MAX_PAGES = 20;
const SHOW = 50;

interface PullPage {
  data: Record<string, unknown>[];
  nextCursor: string | null;
  hasMore: boolean;
}

export async function GET() {
  const config = testConsumerConfig();
  if (!config) return new NextResponse('Not found', { status: 404 });
  const headers = { Authorization: `Bearer ${config.key}` };
  const sourcesRes = await fetch(`${config.backend}/api/v1/lead-capture/sources`, { headers, cache: 'no-store' });
  if (!sourcesRes.ok) {
    return NextResponse.json(await sourcesRes.json().catch(() => ({})), { status: sourcesRes.status });
  }
  const sources = ((await sourcesRes.json()) as { data: unknown[] }).data;
  // The pull API reads oldest first with a cursor: walk it, keep the newest.
  let leads: Record<string, unknown>[] = [];
  let cursor: string | null = null;
  for (let i = 0; i < MAX_PAGES; i += 1) {
    const qs = new URLSearchParams({ limit: '100' });
    if (cursor) qs.set('cursor', cursor);
    const res = await fetch(`${config.backend}/api/v1/lead-capture/leads?${qs.toString()}`, { headers, cache: 'no-store' });
    if (!res.ok) break;
    const page = (await res.json()) as PullPage;
    leads = leads.concat(page.data).slice(-SHOW);
    cursor = page.nextCursor;
    if (!page.hasMore) break;
  }
  return NextResponse.json({ sources, leads: leads.reverse() });
}
