import { describe, expect, it } from 'vitest';
import { mockNumberingService } from './numbering-service.mock';

describe('mockNumberingService', () => {
  it('getCatalog() returns the shaped catalog with resolved + default fields', async () => {
    const items = await mockNumberingService.getCatalog();
    const invoice = items.find((i) => i.docType === 'invoice');
    expect(invoice).toBeDefined();
    expect(invoice!.module).toBe('finance');
    expect(invoice!.prefix).toBe('INV-');
    expect(invoice!.overridePrefix).toBeNull();
    expect(invoice!.nextVal).toBe(1);
    expect(invoice!.sample).toMatch(/INV-\d{4}-00001/);
  });

  it('setFormat() overrides prefix/format/reset and surfaces the override + sample', async () => {
    await mockNumberingService.setFormat('invoice', {
      prefix: 'BILL-',
      formatPattern: '{prefix}{NNNN}',
      reset: 'never',
    });
    const items = await mockNumberingService.getCatalog();
    const invoice = items.find((i) => i.docType === 'invoice')!;
    expect(invoice.prefix).toBe('BILL-');
    expect(invoice.overridePrefix).toBe('BILL-');
    expect(invoice.reset).toBe('never');
    expect(invoice.sample).toBe('BILL-0001');
  });

  it('setNextVal() changes the next generated sample', async () => {
    await mockNumberingService.setFormat('quotation', {
      prefix: 'Q-',
      formatPattern: '{prefix}{NNNN}',
      reset: 'never',
    });
    await mockNumberingService.setNextVal('quotation', 77);
    const items = await mockNumberingService.getCatalog();
    const q = items.find((i) => i.docType === 'quotation')!;
    expect(q.nextVal).toBe(77);
    expect(q.sample).toBe('Q-0077');
  });

  it('resetFormat() drops the override back to the default', async () => {
    await mockNumberingService.setFormat('document_no', {
      prefix: 'X-',
      formatPattern: '{prefix}{NN}',
      reset: 'monthly',
    });
    await mockNumberingService.resetFormat('document_no');
    const items = await mockNumberingService.getCatalog();
    const d = items.find((i) => i.docType === 'document_no')!;
    expect(d.overridePrefix).toBeNull();
    expect(d.prefix).toBe('DOC-');
  });
});
