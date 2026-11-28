import { describe, expect, it } from 'vitest';
import { ACTION_CATALOG, catalogEntry } from './workflow-catalog';

describe('hub connector catalog entries', () => {
  it('registers the customer view action, module-tagged', () => {
    const entry = ACTION_CATALOG.find((e) => e.type === 'hub_connector.customer_view');
    expect(entry?.kind).toBe('action');
    expect(entry?.module).toBe('hub_connector');
    expect(entry?.label).toBe('Hub customer availability');
    expect(entry?.fields.map((f) => f.key)).toEqual(['hubCode', 'customerCode', 'productCodes', 'offset']);
    expect(entry?.fields.filter((f) => f.required).map((f) => f.key)).toEqual(['hubCode', 'customerCode']);
    expect(entry?.fields.every((f) => f.mergeable)).toBe(true);
    expect(entry?.outputs?.map((o) => o.key)).toEqual(['customerName', 'total', 'inStockCount', 'summary', 'nextOffset']);
    expect(catalogEntry('hub_connector.customer_view')).toBe(entry);
  });

  it('registers the stock sync action with no fields', () => {
    const entry = ACTION_CATALOG.find((e) => e.type === 'hub_connector.sync_now');
    expect(entry?.module).toBe('hub_connector');
    expect(entry?.label).toBe('Sync hub stock now');
    expect(entry?.fields).toEqual([]);
    expect(entry?.outputs?.map((o) => o.key)).toEqual(['products', 'queued']);
  });
});
