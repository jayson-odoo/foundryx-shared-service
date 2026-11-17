import { FEEDBACK_REDIRECTS as RULES } from './feedback-redirects.mjs';

export interface FeedbackRedirect {
  source: string;
  destination: string;
  permanent: true;
}

export const FEEDBACK_REDIRECTS: FeedbackRedirect[] = RULES;

function toRegex(source: string): RegExp {
  const body = source
    .split('/')
    .map((seg) => {
      if (seg === ':path*') return '(?:/(?<path>.*))?';
      return seg ? `/${seg.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}` : '';
    })
    .join('');
  return new RegExp(`^${body}/?$`);
}

/** The new path an old idea URL redirects to (first matching rule, the same
 * order Next applies them), or `null` when the path is not an old idea URL. */
export function feedbackRedirectFor(pathname: string): string | null {
  for (const r of FEEDBACK_REDIRECTS) {
    const m = toRegex(r.source).exec(pathname);
    if (!m) continue;
    const rest = m.groups?.path;
    return r.destination.replace('/:path*', rest ? `/${rest}` : '');
  }
  return null;
}
