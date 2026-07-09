import { describe, expect, it } from 'vitest';

import {
  fromMetaComponents,
  toMetaComponents,
  validateDoc,
  qualityLabel,
  distinctVarCount,
} from './whatsapp-template';
import type { WaTemplateDoc } from '@/types/whatsapp-template';

const full: WaTemplateDoc = {
  name: 'order_update',
  category: 'UTILITY',
  language: 'en_US',
  header: { format: 'TEXT', text: 'Hi {{1}}', example: 'Sam' },
  body: { text: 'Order {{1}} is {{2}}.', examples: ['A1', 'shipped'] },
  footer: { text: 'Thanks' },
  buttons: [
    { type: 'QUICK_REPLY', text: 'Track' },
    { type: 'URL', text: 'Open', url: 'https://x.com/{{1}}', example: 'id1' },
    { type: 'PHONE_NUMBER', text: 'Call', phoneNumber: '+60123456789' },
    { type: 'COPY_CODE', example: 'SAVE10' },
  ],
};

describe('toMetaComponents — parity golden (pins FE ⇄ BE transform, SEC-5)', () => {
  it('produces the exact Meta component array the backend emits', () => {
    // This golden is the verified backend `to_meta_components` output.
    expect(toMetaComponents(full)).toEqual([
      { type: 'HEADER', format: 'TEXT', text: 'Hi {{1}}', example: { header_text: ['Sam'] } },
      { type: 'BODY', text: 'Order {{1}} is {{2}}.', example: { body_text: [['A1', 'shipped']] } },
      { type: 'FOOTER', text: 'Thanks' },
      {
        type: 'BUTTONS',
        buttons: [
          { type: 'QUICK_REPLY', text: 'Track' },
          { type: 'URL', text: 'Open', url: 'https://x.com/{{1}}', example: ['id1'] },
          { type: 'PHONE_NUMBER', text: 'Call', phone_number: '+60123456789' },
          { type: 'COPY_CODE', example: 'SAVE10' },
        ],
      },
    ]);
  });

  it('media header → header_handle example', () => {
    const comps = toMetaComponents({
      ...full,
      header: { format: 'IMAGE', sampleKey: 'conn:1:abc' },
    });
    expect(comps[0]).toEqual({ type: 'HEADER', format: 'IMAGE', example: { header_handle: ['conn:1:abc'] } });
  });
});

describe('round-trip', () => {
  it('fromMetaComponents(toMetaComponents(doc)) preserves the doc', () => {
    const back = fromMetaComponents(toMetaComponents(full), {
      name: 'order_update',
      category: 'UTILITY',
      language: 'en_US',
    });
    expect(back.header).toEqual({ format: 'TEXT', text: 'Hi {{1}}', example: 'Sam' });
    expect(back.body).toEqual({ text: 'Order {{1}} is {{2}}.', examples: ['A1', 'shipped'] });
    expect(back.footer).toEqual({ text: 'Thanks' });
    expect(back.buttons?.map((b) => b.type)).toEqual(['QUICK_REPLY', 'URL', 'PHONE_NUMBER', 'COPY_CODE']);
    expect(back.buttons?.[1]).toMatchObject({ url: 'https://x.com/{{1}}', example: 'id1' });
    expect(back.buttons?.[2]).toMatchObject({ phoneNumber: '+60123456789' });
  });
});

describe('validateDoc (mirrors backend 422 gate)', () => {
  const ok: WaTemplateDoc = { name: 'good', category: 'UTILITY', language: 'en', body: { text: 'Hi', examples: [] } };

  it('passes a valid minimal doc', () => {
    expect(validateDoc(ok)).toEqual({});
  });
  it('rejects a bad name', () => {
    expect(validateDoc({ ...ok, name: 'Bad Name!' }).name).toBeTruthy();
  });
  it('rejects a duplicate name', () => {
    expect(validateDoc(ok, new Set(['good'])).name).toBeTruthy();
  });
  it('rejects an empty body', () => {
    expect(validateDoc({ ...ok, body: { text: '  ', examples: [] } }).body).toBeTruthy();
  });
  it('rejects a sample-count mismatch', () => {
    expect(validateDoc({ ...ok, body: { text: 'Hi {{1}} {{2}}', examples: ['one'] } }).body).toBeTruthy();
  });
  it('accepts a matching sample count', () => {
    expect(validateDoc({ ...ok, body: { text: 'Hi {{1}}, order {{2}} shipped', examples: ['a', 'b'] } })).toEqual({});
  });

  it('rejects a body ending with a variable (Meta rule)', () => {
    expect(validateDoc({ ...ok, body: { text: 'Your order is {{1}}', examples: ['a'] } }).body).toBeTruthy();
  });

  it('rejects two adjacent variables (Meta rule)', () => {
    expect(validateDoc({ ...ok, body: { text: 'Hi {{1}} {{2}} welcome', examples: ['a', 'b'] } }).body).toBeTruthy();
  });
  it('rejects a bad URL button', () => {
    expect(validateDoc({ ...ok, buttons: [{ type: 'URL', text: 'x', url: 'ftp://no' }] }).buttons).toBeTruthy();
  });
  it('rejects > 10 buttons', () => {
    const buttons = Array.from({ length: 11 }, (_v, i) => ({ type: 'QUICK_REPLY' as const, text: `b${i}` }));
    expect(validateDoc({ ...ok, buttons }).buttons).toBeTruthy();
  });
  it('rejects non-sequential variables ({{1}} {{3}})', () => {
    expect(validateDoc({ ...ok, body: { text: 'Hi {{1}} and {{3}}', examples: ['a', 'b'] } }).body).toBeTruthy();
  });
});

describe('stale header example', () => {
  it('drops a header example when the text has no variable', () => {
    const comps = toMetaComponents({
      name: 'h',
      category: 'UTILITY',
      language: 'en',
      header: { format: 'TEXT', text: 'No vars', example: 'stale' },
      body: { text: 'Hi', examples: [] },
    });
    expect(comps[0]).toEqual({ type: 'HEADER', format: 'TEXT', text: 'No vars' });
  });
});

describe('helpers', () => {
  it('distinctVarCount counts distinct placeholders', () => {
    expect(distinctVarCount('{{1}} {{2}} {{1}}')).toBe(2);
  });
  it('qualityLabel maps GREEN/YELLOW/RED', () => {
    expect(qualityLabel('GREEN')).toBe('High');
    expect(qualityLabel('YELLOW')).toBe('Medium');
    expect(qualityLabel('RED')).toBe('Low');
    expect(qualityLabel(null)).toBe('—');
  });
});
