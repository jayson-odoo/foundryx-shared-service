/**
 * Scheme-validated link splitting for untrusted, visitor-authored text
 * (plan 34 / A7b, D-A7B-26/AC-WEB-48 - the house anti-SSTI line applied on
 * the client). Text nodes only: this module never returns HTML, never
 * touches `dangerouslySetInnerHTML`, and a segment only becomes a link after
 * `new URL(...)` confirms an `http:`/`https:` scheme - a `javascript:` or
 * `data:` payload (or anything the URL parser rejects) renders as the exact
 * literal text instead.
 */
export interface LinkifySegment {
  type: 'text' | 'link';
  value: string;
  /** Set only for `type === 'link'` - identical to `value`, kept separate so
   *  a caller never has to re-derive the href from display text. */
  href?: string;
}

const URL_PATTERN = /(https?:\/\/[^\s<>"']+)/gi;
const TRAILING_PUNCTUATION = /[).,!?;:]+$/;

function isSafeHref(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === 'http:' || url.protocol === 'https:';
  } catch {
    return false;
  }
}

/** Splits `text` into plain-text and link segments. Renderers must map
 *  `type: 'text'` segments to a text node and `type: 'link'` segments to an
 *  anchor whose `href` is this segment's OWN `href` field - never the raw
 *  source string re-parsed client-side. */
export function linkifySegments(text: string): LinkifySegment[] {
  const segments: LinkifySegment[] = [];
  let lastIndex = 0;

  for (const match of Array.from(text.matchAll(URL_PATTERN))) {
    const start = match.index ?? 0;
    if (start > lastIndex) {
      segments.push({ type: 'text', value: text.slice(lastIndex, start) });
    }
    const raw = match[0];
    const trailingMatch = raw.match(TRAILING_PUNCTUATION);
    const trailing = trailingMatch ? trailingMatch[0] : '';
    const candidate = trailing ? raw.slice(0, raw.length - trailing.length) : raw;

    if (isSafeHref(candidate)) {
      segments.push({ type: 'link', value: candidate, href: candidate });
      if (trailing) segments.push({ type: 'text', value: trailing });
    } else {
      segments.push({ type: 'text', value: raw });
    }
    lastIndex = start + raw.length;
  }

  if (lastIndex < text.length) {
    segments.push({ type: 'text', value: text.slice(lastIndex) });
  }
  if (segments.length === 0) {
    segments.push({ type: 'text', value: text });
  }
  return segments;
}
