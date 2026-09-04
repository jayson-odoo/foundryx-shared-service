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
