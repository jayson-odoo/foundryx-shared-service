import { describe, expect, it } from 'vitest';
import {
  MAX_LOOKUPS,
  aliasCollision,
  canTestLookup,
  earlierAliases,
  emptyLookup,
  localColumnOptions,
  validateAliasFormat,
  validateLookupPath,
} from './autocount-lookups';
import type { AutocountLookupSpec } from '@/types/autocount';

describe('validateLookupPath (mirrors validate_http_path)', () => {
  it('accepts a clean absolute path', () => {
    expect(validateLookupPath('/itemuombypage')).toBeNull();
  });
  it.each([
    ['', 'Enter an endpoint path.'],
    ['itembypage', 'Path must start with /.'],
    ['/a/../b', 'Path must not contain "..".'],
    ['/a?b=1', 'Path must not carry a query string.'],
    ['/' + 'a'.repeat(200), 'Path must be 200 characters or fewer.'],
  ])('rejects %s', (path, message) => {
    expect(validateLookupPath(path)).toBe(message);
  });
});

describe('validateAliasFormat', () => {
  it('accepts a letter-led identifier', () => {
    expect(validateAliasFormat('BaseUOMPrice')).toBeNull();
  });
  it('rejects blank', () => {
    expect(validateAliasFormat('')).toBe('Name the field.');
  });
  it('rejects a leading digit', () => {
    expect(validateAliasFormat('1price')).toMatch(/letters, digits and underscore/);
  });
});

function lookup(overrides: Partial<AutocountLookupSpec> = {}): AutocountLookupSpec {
  return {
    path: '/itemuombypage',
    as: 'uom',
    on: [{ local: 'ItemCode', remote: 'ItemCode' }],
    fields: [{ remote: 'Price', as: 'BaseUOMPrice' }],
    ...overrides,
  };
}

describe('earlierAliases / localColumnOptions (AC-10-02 multi-hop)', () => {
  it('a second lookup may join on the first lookup own alias', () => {
    const lookups = [lookup(), lookup({ path: '/other', fields: [{ remote: 'X', as: 'Y' }] })];
    expect(earlierAliases(lookups, 1)).toEqual(['BaseUOMPrice']);
    expect(localColumnOptions(['ItemCode'], lookups, 1)).toEqual(['ItemCode', 'BaseUOMPrice']);
  });

  it('a later lookup alias is NOT visible to an earlier one', () => {
    const lookups = [lookup(), lookup({ path: '/other', fields: [{ remote: 'X', as: 'Y' }] })];
    expect(earlierAliases(lookups, 0)).toEqual([]);
  });
});

describe('aliasCollision (AC-10-01 save-time mirror)', () => {
  it('collides with a source column', () => {
    expect(aliasCollision('ItemCode', ['ItemCode'], [lookup()], 0, 0)).toMatch(/already a source column/);
  });

  it('collides with an earlier lookup alias', () => {
    const lookups = [lookup(), lookup({ path: '/other', fields: [{ remote: 'X', as: 'BaseUOMPrice' }] })];
    expect(aliasCollision('BaseUOMPrice', [], lookups, 1, 0)).toMatch(/already used by another/);
  });

  it('a later lookup naming the SAME alias its own earlier lookup already owns is fine when excluding self', () => {
    const lookups = [lookup()];
    expect(aliasCollision('BaseUOMPrice', [], lookups, 0, 0)).toBeNull();
  });

  it('bad format is reported before a collision check runs', () => {
    expect(aliasCollision('1bad', [], [lookup()], 0, 0)).toMatch(/letters, digits/);
  });
});

describe('emptyLookup / canTestLookup / MAX_LOOKUPS', () => {
  it('a fresh lookup has one empty join pair and no fields', () => {
    const l = emptyLookup(0);
    expect(l.on).toHaveLength(1);
    expect(l.fields).toHaveLength(0);
    expect(l.as).toBe('lookup1');
  });

  it('Test is disabled until the path is valid', () => {
    expect(canTestLookup(emptyLookup(0))).toBe(false);
    expect(canTestLookup(lookup())).toBe(true);
  });

  it('MAX_LOOKUPS is 5 (AC-10-01)', () => {
    expect(MAX_LOOKUPS).toBe(5);
  });
});
