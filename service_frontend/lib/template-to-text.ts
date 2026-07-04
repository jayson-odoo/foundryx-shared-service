import type { TemplateDocument } from '@/types/templates';

/**
 * Flatten a template block-document to plain text + merge tokens — used when a
 * template is loaded as a STARTING POINT into an inline subject/body editor
 * (BL-081 "copy" behavior). Rich blocks (brand header/footer, images, social)
 * have no plain-text form and are dropped; headings/paragraphs/buttons keep
 * their text and any `{{merge}}` tokens.
 */
function stripHtml(html: string): string {
  return html
    .replace(/<\s*br\s*\/?>/gi, '\n')
    .replace(/<\/(p|div|li|h[1-6])>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/[ \t]+\n/g, '\n')
    .trim();
}

export function templateDocToText(doc: TemplateDocument): string {
  const parts: string[] = [];
  for (const section of doc.sections ?? []) {
    for (const column of section.columns ?? []) {
      for (const block of column.blocks ?? []) {
        if (block.type === 'heading' && block.text.trim()) {
          parts.push(block.text.trim());
        } else if (block.type === 'text') {
          const text = stripHtml(block.html);
          if (text) parts.push(text);
        } else if (block.type === 'button' && block.label.trim()) {
          parts.push(`${block.label.trim()}: ${block.href}`);
        }
      }
    }
  }
  return parts.join('\n\n');
}
