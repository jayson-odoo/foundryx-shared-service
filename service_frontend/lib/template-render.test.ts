/**
 * Mock-phase renderer (plan sprint-2/07) — merge substitution semantics (D5):
 * {{dotted.path}} only, HTML-escaped values, missing = '' on send / loud in
 * preview. The production renderer is the Phase-B backend pipeline.
 */
import { describe, expect, it } from 'vitest';
import { createBlankDocument, createBlock, insertBlock } from './template-doc';
import {
  escapeHtml,
  renderDocumentHtml,
  renderDocumentText,
  renderMergeTokens,
} from './template-render';

describe('renderMergeTokens', () => {
  it('substitutes dotted paths', () => {
    expect(renderMergeTokens('Hi {{user.name}}!', { 'user.name': 'Alex' })).toBe('Hi Alex!');
  });

  it('HTML-escapes substituted values (XSS via attendee name)', () => {
    const out = renderMergeTokens('Hi {{name}}', { name: '<script>alert(1)</script>' });
    expect(out).not.toContain('<script>');
    expect(out).toContain('&lt;script&gt;');
  });

  it('missing fact: empty string in send mode, loud token in preview', () => {
    expect(renderMergeTokens('A{{missing}}B', {}, 'send')).toBe('AB');
    expect(renderMergeTokens('A{{missing}}B', {}, 'preview')).toContain('missing');
  });

  it('does NOT evaluate expressions — substitution only (D5, no SSTI surface)', () => {
    // A Jinja-style escalation probe is just an unknown fact key: blanked.
    expect(renderMergeTokens('{{__class__.__init__}}', {}, 'send')).toBe('');
    // Operators/filters are not even tokenized — left verbatim.
    expect(renderMergeTokens('{{ 7 * 7 }}', {}, 'send')).toBe('{{ 7 * 7 }}');
    expect(renderMergeTokens('{{name|upper}}', { name: 'x' }, 'send')).toBe('{{name|upper}}');
  });
});

describe('escapeHtml', () => {
  it('escapes the five specials', () => {
    expect(escapeHtml(`&<>"'`)).toBe('&amp;&lt;&gt;&quot;&#39;');
  });
});

describe('renderDocumentHtml / renderDocumentText', () => {
  it('renders blocks with substituted facts + brand values', () => {
    let doc = createBlankDocument();
    const section = doc.sections[1];
    const heading = createBlock('heading');
    if (heading.type === 'heading') heading.text = 'Hi {{recipient.firstName}},';
    const button = createBlock('button');
    if (button.type === 'button') {
      button.label = 'Reset';
      button.href = '{{resetLink}}';
    }
    doc = insertBlock(doc, section.id, section.columns[0].id, heading);
    doc = insertBlock(doc, section.id, section.columns[0].id, button);

    const html = renderDocumentHtml(doc, {
      'recipient.firstName': 'Alex',
      resetLink: 'https://example.com/reset?token=t',
    });
    expect(html).toContain('Hi Alex,');
    expect(html).toContain('href="https://example.com/reset?token=t"');
    // Brand footer renders from brand values (mock brand).
    expect(html).toContain('Acme Events');

    const text = renderDocumentText(doc, {
      'recipient.firstName': 'Alex',
      resetLink: 'https://example.com/reset?token=t',
    });
    expect(text).toContain('Hi Alex,');
    expect(text).toContain('https://example.com/reset?token=t');
  });
});
