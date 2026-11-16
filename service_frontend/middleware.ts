import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

import { validateEmbedOrigin } from './lib/embed-origin';

/**
 * frame-ancestors clickjacking guard for the chromeless embed surfaces:
 *  - the omnichannel embed shell (sprint-4/11 AC-11H-15) - `?c=<connectionId>`.
 *  - the web chat PANEL (plan 34 / A7b S4, D-A7B-11/AC-WEB-47) -
 *    `/public/webchat/{widgetKey}`.
 * Both resolve their own `allowedOrigins` from a tiny public backend GET and
 * emit `Content-Security-Policy: frame-ancestors <origins>`. Unknown / dead
 * key → `frame-ancestors 'none'` (fail closed - nothing may frame it).
 *
 * The personal feedback BOARD (`/public/feedback/board/**`, lane
 * SS-FEEDBACK-BOARD-LINK) is framed by the Sorento CRM public page
 * (`documentation/ideation/feedback-link-contract.md` section 3), so it allows
 * `'self'` + the deployment's CRM origins from env - see `boardFrameAncestors`.
 */
const BACKEND =
  process.env.BACKEND_API_URL ??
  process.env.NEXT_PUBLIC_BACKEND_API_URL ??
  'http://localhost:8001';

export const config = {
  matcher: ['/embed/omnichannel/:path*', '/public/webchat/:widgetKey*', '/public/feedback/board/:path*'],
};

const BOARD_PREFIX = '/public/feedback/board/';
const DEFAULT_BOARD_FRAME_ANCESTORS = 'https://fe-sorento.foundryx.my';

/**
 * `frame-ancestors` source list for the feedback board: `'self'` + every
 * valid bare origin in `FEEDBACK_BOARD_FRAME_ANCESTORS` (comma / space
 * separated; unset = the prod CRM origin; empty = same-origin only). Each entry
 * goes through the embed-origin rule (https only except localhost, no path,
 * no wildcard, no special characters), so a config typo can never widen the
 * policy or inject another CSP directive - an invalid entry is dropped.
 * Read per request (server env, never inlined at build).
 */
export function boardFrameAncestors(): string {
  const raw = process.env.FEEDBACK_BOARD_FRAME_ANCESTORS ?? DEFAULT_BOARD_FRAME_ANCESTORS;
  const origins = new Set<string>();
  for (const entry of raw.split(/[\s,]+/)) {
    if (!entry) continue;
    const check = validateEmbedOrigin(entry);
    if (check.ok && check.value) origins.add(check.value);
  }
  return ["'self'", ...Array.from(origins)].join(' ');
}

/**
 * Review round 2 (B4) - a THIS-REQUEST-ONLY fail-closed result, never a
 * cached/shared one: every call is independent, so one caller's failure can
 * never widen the blast radius to another widget key's request. The failure
 * shapes are logged distinctly so an operator can tell "the backend
 * genuinely has no origins for this key" (silent - not an error, the normal
 * shape for an unknown key) from "the backend call itself failed" (a 5xx, a
 * 429, a network error, or - review round 3, N-new-5 - a 200 whose body
 * isn't the expected JSON shape at all; a healthy caller answering 200 with
 * an empty list is indistinguishable from any of these without the logging).
 */
async function fetchAllowedOrigins(url: string): Promise<string[]> {
  let response: Response;
  try {
    response = await fetch(url, { headers: { accept: 'application/json' } });
  } catch (err) {
    console.warn(`webchat frame-policy fetch failed (network): ${url}`, err);
    return [];
  }
  if (!response.ok) {
    console.warn(`webchat frame-policy fetch failed: ${url} status=${response.status}`);
    return [];
  }
  // N-new-5 (review round 3): a 200 whose body is not the expected JSON shape
  // (a captive proxy, a CDN error page, a content-type mismatch) must fail
  // closed for THIS request the same way a non-2xx does, never propagate out
  // of `middleware()` as an uncaught error.
  try {
    const body = (await response.json()) as { allowedOrigins?: string[] };
    return Array.isArray(body.allowedOrigins) ? body.allowedOrigins : [];
  } catch (err) {
    console.warn(`webchat frame-policy fetch failed (bad body): ${url} status=${response.status}`, err);
    return [];
  }
}

export async function middleware(req: NextRequest): Promise<NextResponse> {
  const res = NextResponse.next();
  const { pathname, searchParams } = req.nextUrl;

  if (pathname.startsWith(BOARD_PREFIX)) {
    res.headers.set('Content-Security-Policy', `frame-ancestors ${boardFrameAncestors()}`);
    // X-Frame-Options overrides the CSP in some browsers: never on the board.
    res.headers.delete('X-Frame-Options');
    return res;
  }

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
