/**
 * Minimal client-side HTML sanitizer (defense-in-depth, plan sprint-2/07).
 *
 * The canvas Text block renders stored block HTML via dangerouslySetInnerHTML
 * in the app origin. The content is already nh3-sanitized server-side and the
 * only authoring path is the execCommand-limited RichTextField - but a doc
 * loaded from any other source must never execute script in-origin. This
 * strips script/style/iframe/object elements, on* event attributes, and
 * javascript:/data: URLs from href/src before injection.
 *
 * Not a substitute for the server sanitizer (nh3) - that stays the gate for
 * what gets PERSISTED and sent; this is the render-time net.
 */
const URL_ATTRS = ['href', 'src', 'xlink:href'];
const BAD_TAGS = new Set(['SCRIPT', 'STYLE', 'IFRAME', 'OBJECT', 'EMBED', 'LINK', 'META', 'BASE']);

export function sanitizeHtml(html: string): string {
  if (typeof document === 'undefined') return html; // SSR: never inject anyway
  const template = document.createElement('template');
  template.innerHTML = html;

  const walk = (node: ParentNode) => {
    for (const child of Array.from(node.children)) {
      if (BAD_TAGS.has(child.tagName)) {
        child.remove();
        continue;
      }
      for (const attr of Array.from(child.attributes)) {
        const name = attr.name.toLowerCase();
        if (name.startsWith('on')) {
          child.removeAttribute(attr.name);
          continue;
        }
        if (URL_ATTRS.includes(name)) {
          const value = attr.value.trim().toLowerCase();
          if (value.startsWith('javascript:') || value.startsWith('data:')) {
            child.removeAttribute(attr.name);
          }
        }
      }
      walk(child);
    }
  };

  walk(template.content);
  return template.innerHTML;
}
