import { describe, expect, it } from 'vitest';
import type { TemplateDocument } from '@/types/templates';
import { templateDocToText } from './template-to-text';

function doc(blocks: unknown[]): TemplateDocument {
  return {
    schemaVersion: 1,
    sections: [{ id: 's', layout: '100', background: null, padding: { top: 0, bottom: 0, left: 0, right: 0 }, columns: [{ id: 'c', blocks: blocks as never }] }],
  } as TemplateDocument;
}

describe('templateDocToText', () => {
  it('flattens headings, text (HTML stripped) and buttons, keeping merge tokens', () => {
    const out = templateDocToText(
      doc([
        { id: 'b1', type: 'heading', text: '{{recordLabel}} is now {{toStatus}}', level: 2, align: 'left' },
        { id: 'b2', type: 'text', html: 'Moved from <b>{{fromStatus}}</b> to {{toStatus}}.', align: 'left' },
        { id: 'b3', type: 'button', label: 'View', href: '{{link}}', align: 'left', backgroundColor: null, textColor: null, borderRadius: 6 },
      ]),
    );
    expect(out).toBe(
      '{{recordLabel}} is now {{toStatus}}\n\nMoved from {{fromStatus}} to {{toStatus}}.\n\nView: {{link}}',
    );
  });

  it('drops blocks with no plain-text form (brand header/footer, image)', () => {
    const out = templateDocToText(
      doc([
        { id: 'h', type: 'brandHeader', overrides: null },
        { id: 't', type: 'text', html: 'Hello', align: 'left' },
        { id: 'f', type: 'brandFooter', overrides: null },
      ]),
    );
    expect(out).toBe('Hello');
  });
});
