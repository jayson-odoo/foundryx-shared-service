import { describe, expect, it } from 'vitest';
import {
  buildListNav,
  decodeListQuery,
  encodeListQuery,
  parseListNav,
} from './list-context';
import type { ListQuery } from '@/types/resource';

const QUERY: ListQuery = {
  page: 2,
  pageSize: 25,
  search: 'jay',
  sort: { id: 'name', desc: false },
  filter: null,
  statusView: 'active',
  segment: undefined,
};

describe('encodeListQuery / decodeListQuery (existing contract, unchanged)', () => {
  it('round-trips', () => {
    const encoded = encodeListQuery(QUERY);
    expect(decodeListQuery(encoded)).toEqual(QUERY);
  });

  it('decodes null/undefined/garbage to null', () => {
    expect(decodeListQuery(null)).toBeNull();
    expect(decodeListQuery(undefined)).toBeNull();
    expect(decodeListQuery('not-base64-json!!!')).toBeNull();
  });
});

/** URL-safe base64 (matches encodeListQuery's own alphabet, no dependency on it). */
function toCtx(obj: unknown): string {
  const json = JSON.stringify(obj);
  const b64 = typeof window === 'undefined' ? Buffer.from(json).toString('base64') : window.btoa(json);
  return b64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

describe('decodeListQuery shape guard (fix round 2)', () => {
  it('rejects a foreign-shape payload (valid JSON, wrong shape) instead of trusting it', () => {
    expect(decodeListQuery(toCtx({ foo: 'bar' }))).toBeNull();
    expect(decodeListQuery(toCtx('a plain string'))).toBeNull();
    expect(decodeListQuery(toCtx(42))).toBeNull();
    expect(decodeListQuery(toCtx(null))).toBeNull();
    expect(decodeListQuery(toCtx([1, 2, 3]))).toBeNull();
  });

  it('rejects non-integer/negative page or pageSize', () => {
    expect(decodeListQuery(toCtx({ page: -1, pageSize: 25 }))).toBeNull();
    expect(decodeListQuery(toCtx({ page: 1.5, pageSize: 25 }))).toBeNull();
    expect(decodeListQuery(toCtx({ page: '1', pageSize: 25 }))).toBeNull();
    expect(decodeListQuery(toCtx({ page: 0, pageSize: -5 }))).toBeNull();
  });

  it('rejects an unknown statusView', () => {
    expect(decodeListQuery(toCtx({ page: 0, pageSize: 25, statusView: 'deleted' }))).toBeNull();
  });

  it('rejects a malformed sort/filter/search of the wrong type', () => {
    expect(decodeListQuery(toCtx({ page: 0, pageSize: 25, sort: 'name' }))).toBeNull();
    expect(decodeListQuery(toCtx({ page: 0, pageSize: 25, sort: { id: 'name' } }))).toBeNull();
    expect(decodeListQuery(toCtx({ page: 0, pageSize: 25, filter: 'active' }))).toBeNull();
    expect(decodeListQuery(toCtx({ page: 0, pageSize: 25, filter: { kind: 'condition' } }))).toBeNull();
    expect(decodeListQuery(toCtx({ page: 0, pageSize: 25, search: 123 }))).toBeNull();
  });

  it('accepts the minimal valid shape (only page/pageSize) and a fully-populated one', () => {
    expect(decodeListQuery(toCtx({ page: 0, pageSize: 25 }))).toEqual({ page: 0, pageSize: 25 });
    const full = {
      page: 2,
      pageSize: 10,
      search: 'jay',
      sort: { id: 'name', desc: true },
      filter: {
        kind: 'group',
        combinator: 'and',
        rules: [{ kind: 'condition', field: 'status', operator: 'eq', value: 'active' }],
      },
      statusView: 'trashed',
      segment: 'pending',
    };
    expect(decodeListQuery(toCtx(full))).toEqual(full);
  });
});

describe('buildListNav (AC-DLA-29/30/31)', () => {
  it('appends ctx/i/from onto a bare path', () => {
    const href = buildListNav('/user-management/users/u1', { ctx: 'CTX', i: 4, from: 'u1' });
    const url = new URL(href, 'http://x');
    expect(url.pathname).toBe('/user-management/users/u1');
    expect(url.searchParams.get('ctx')).toBe('CTX');
    expect(url.searchParams.get('i')).toBe('4');
    expect(url.searchParams.get('from')).toBe('u1');
  });

  it('merges onto an href that already carries its own params (e.g. ?edit=1)', () => {
    const href = buildListNav('/documents/types?edit=t1', { ctx: 'CTX', i: 0, from: 't1' });
    const url = new URL(href, 'http://x');
    expect(url.searchParams.get('edit')).toBe('t1');
    expect(url.searchParams.get('ctx')).toBe('CTX');
    expect(url.searchParams.get('from')).toBe('t1');
  });

  it('a null/undefined value DELETES that key rather than leaving a stale one', () => {
    const href = buildListNav('/x?ctx=STALE&from=STALE', { ctx: null, i: null, from: null });
    const url = new URL(href, 'http://x');
    expect(url.searchParams.has('ctx')).toBe(false);
    expect(url.searchParams.has('i')).toBe(false);
    expect(url.searchParams.has('from')).toBe(false);
  });

  it('an OMITTED key leaves the href\'s own value alone (regression: use-record-nav calling with only {from} must not drop the ctx buildHref already embedded)', () => {
    const href = buildListNav('/records/r2?ctx=CTX&i=1', { from: 'r2' });
    const url = new URL(href, 'http://x');
    expect(url.searchParams.get('ctx')).toBe('CTX');
    expect(url.searchParams.get('i')).toBe('1');
    expect(url.searchParams.get('from')).toBe('r2');
  });

  it('preserves a trailing hash', () => {
    const href = buildListNav('/records/r1#comments', { ctx: 'CTX', i: 0, from: 'r1' });
    expect(href.endsWith('#comments')).toBe(true);
    expect(href).toContain('ctx=CTX');
  });

});

describe('parseListNav (AC-DLA-29/30/31)', () => {
  it('reads ctx/i/from back off a URLSearchParams', () => {
    const params = new URLSearchParams('ctx=CTX&i=7&from=r9');
    expect(parseListNav(params)).toEqual({ ctx: 'CTX', i: 7, from: 'r9' });
  });

  it('missing params come back null', () => {
    const params = new URLSearchParams('');
    expect(parseListNav(params)).toEqual({ ctx: null, i: null, from: null });
  });

  it('a non-integer or negative i comes back null (never NaN/negative)', () => {
    expect(parseListNav(new URLSearchParams('i=abc')).i).toBeNull();
    expect(parseListNav(new URLSearchParams('i=-1')).i).toBeNull();
    expect(parseListNav(new URLSearchParams('i=3.5')).i).toBeNull();
  });
});
