import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

/**
 * frame-ancestors clickjacking guard for the chromeless embed surfaces:
 *  - the omnichannel embed shell (sprint-4/11 AC-11H-15) - `?c=<connectionId>`.
 *  - the web chat PANEL (plan 34 / A7b S4, D-A7B-11/AC-WEB-47) -
 *    `/public/webchat/{widgetKey}`.
 * Both resolve their own `allowedOrigins` from a tiny public backend GET and
 * emit `Content-Security-Policy: frame-ancestors <origins>`. Unknown / dead
 * key → `frame-ancestors 'none'` (fail closed - nothing may frame it).
 */
const BACKEND =
  process.env.BACKEND_API_URL ??
  process.env.NEXT_PUBLIC_BACKEND_API_URL ??
  'http://localhost:8001';

export const config = {
  matcher: ['/embed/omnichannel/:path*', '/public/webchat/:widgetKey*'],
};

async function fetchAllowedOrigins(url: string): Promise<string[]> {
  try {
    const r = await fetch(url, { headers: { accept: 'application/json' } });
    if (!r.ok) return [];
    const body = (await r.json()) as { allowedOrigins?: string[] };
    return Array.isArray(body.allowedOrigins) ? body.allowedOrigins : [];
  } catch {
    return [];
  }
}

export async function middleware(req: NextRequest): Promise<NextResponse> {
  const res = NextResponse.next();
  const { pathname, searchParams } = req.nextUrl;

  let origins: string[] = [];
  if (pathname.startsWith('/public/webchat/')) {
    const widgetKey = pathname.split('/')[3];
    if (widgetKey) {
      origins = await fetchAllowedOrigins(
        `${BACKEND}/public/omnichannel/webchat/${encodeURIComponent(widgetKey)}/frame-policy`,
      );
    }
  } else {
    const connectionId = searchParams.get('c');
    if (connectionId) {
      origins = await fetchAllowedOrigins(
        `${BACKEND}/embed/frame-policy?c=${encodeURIComponent(connectionId)}`,
      );
    }
  }

  const ancestors = origins.length > 0 ? origins.join(' ') : "'none'";
  res.headers.set('Content-Security-Policy', `frame-ancestors ${ancestors}`);
  return res;
}
