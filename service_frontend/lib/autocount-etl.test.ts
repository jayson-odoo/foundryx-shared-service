import { describe, expect, it } from 'vitest';
import {
  isDocumentEntity,
  pickerColumnOptions,
  previewBadgeText,
  schemaCompletionConfig,
  starterQuery,
  todayDateString,
} from './autocount-etl';
import type { AutocountSqlPreview, AutocountSqlSchema } from '@/types/autocount';

const SCHEMA: AutocountSqlSchema = {
  connectionId: 'conn-sql-1',
  dialect: 'mssql',
  database: 'AED',
  schemas: [
    {
      name: 'dbo',
      tables: [
        { name: 'Debtor', columns: [{ name: 'AccNo', type: 'varchar' }, { name: 'CompanyName', type: 'nvarchar' }] },
        { name: 'Stock', columns: [{ name: 'ItemCode', type: 'varchar' }] },
      ],
    },
    { name: 'audit', tables: [{ name: 'Log', columns: [{ name: 'Id', type: 'int' }] }] },
  ],
  introspectedAt: '2026-08-30T00:00:00Z',
};

function preview(overrides: Partial<AutocountSqlPreview> = {}): AutocountSqlPreview {
  return {
    columns: [{ name: 'AccNo', type: 'varchar' }],
    rows: [],
    rowCount: 0,
    truncated: false,
    durationMs: 310,
    ...overrides,
  };
}

describe('isDocumentEntity', () => {
  it('flags SO/PO only', () => {
    expect(isDocumentEntity('sales_order')).toBe(true);
    expect(isDocumentEntity('purchase_order')).toBe(true);
    expect(isDocumentEntity('customer')).toBe(false);
    expect(isDocumentEntity('supplier')).toBe(false);
  });
});

describe('pickerColumnOptions', () => {
  it('offers the preview columns first, then saved picks the preview lost', () => {
    expect(pickerColumnOptions(['AccNo', 'Name'], ['Name', 'Legacy'])).toEqual([
      'AccNo',
      'Name',
      'Legacy',
    ]);
  });

  it('is just the saved picks before any preview ran', () => {
    expect(pickerColumnOptions([], ['AccNo'])).toEqual(['AccNo']);
  });
});

describe('previewBadgeText', () => {
  it('states rows + duration, singular for one row', () => {
    expect(previewBadgeText(preview({ rowCount: 1 }))).toBe('1 row · 0.31 s');
    expect(previewBadgeText(preview({ rowCount: 12, durationMs: 1000 }))).toBe('12 rows · 1.00 s');
  });

  it('marks a capped result so 100 never reads as the whole set', () => {
    expect(previewBadgeText(preview({ rowCount: 100, truncated: true }))).toBe(
      '100 rows (first 100) · 0.31 s',
    );
  });
});

describe('schemaCompletionConfig', () => {
  it('keys tables by schema prefix and defaults to the first schema', () => {
    expect(schemaCompletionConfig(SCHEMA)).toEqual({
      schema: {
        'dbo.Debtor': ['AccNo', 'CompanyName'],
        'dbo.Stock': ['ItemCode'],
        'audit.Log': ['Id'],
      },
      defaultSchema: 'dbo',
    });
  });

  it('is empty without a schema', () => {
    expect(schemaCompletionConfig(null)).toEqual({ schema: {} });
  });
});

describe('starterQuery', () => {
  it('is the schema-qualified SELECT *', () => {
    expect(starterQuery('dbo', 'Debtor')).toBe('SELECT * FROM dbo.Debtor');
  });
});

describe('todayDateString', () => {
  it('is a YYYY-MM-DD date', () => {
    expect(todayDateString()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});
