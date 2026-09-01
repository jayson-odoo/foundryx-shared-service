import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

/**
 * frame-ancestors clickjacking guard for the chromeless omnichannel embed
 * routes (sprint-4/11 AC-11H-15). The consumer mounts the iframe with the
 * NON-secret connection id as `?c=<connectionId>` (the assertion itself is
 * NEVER in the URL - it arrives via the postMessage handshake). We resolve that
 * connection's `allowedOrigins` from the backend and emit
 * `Content-Security-Policy: frame-ancestors <origins>`. Unknown / absent
 * connection → `frame-ancestors 'none'` (fail closed - nothing may frame it).
 */
const BACKEND =
  process.env.BACKEND_API_URL ??
  process.env.NEXT_PUBLIC_BACKEND_API_URL ??
  'http://localhost:8001';

export const config = { matcher: '/embed/omnichannel/:path*' };

export async function middleware(req: NextRequest): Promise<NextResponse> {
  const res = NextResponse.next();
  const connectionId = req.nextUrl.searchParams.get('c');
  let origins: string[] = [];
  if (connectionId) {
    try {
      const r = await fetch(
        `${BACKEND}/embed/frame-policy?c=${encodeURIComponent(connectionId)}`,
        { headers: { accept: 'application/json' } },
      );
      if (r.ok) {
        const body = (await r.json()) as { allowedOrigins?: string[] };
        origins = Array.isArray(body.allowedOrigins) ? body.allowedOrigins : [];
      }
    } catch {
      origins = [];
    }
  }
  const ancestors = origins.length > 0 ? origins.join(' ') : "'none'";
  res.headers.set('Content-Security-Policy', `frame-ancestors ${ancestors}`);
  return res;
}
