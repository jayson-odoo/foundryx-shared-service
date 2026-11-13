import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { AutocountCompany } from '@/types/autocount';
import type { DocLookupType } from '@/types/autocount-doc-lookup';
import { DocSearchForm, detectType } from './doc-search-form';

const TYPES: DocLookupType[] = [
  { key: 'delivery_order', label: 'Delivery order', prefixes: ['PS', 'DO'], hasLastModified: true, hasByDocNo: false, connected: true },
  { key: 'goods_receive_note', label: 'Goods received note', prefixes: ['GRN', 'GR'], hasLastModified: true, hasByDocNo: false, connected: false },
];

const COMPANY = { id: 'c1', name: 'SL Trading' } as AutocountCompany;

function renderForm(onSearch = vi.fn(), companyId: string | null = 'c1') {
  render(
    <DocSearchForm
      companies={[COMPANY]}
      types={TYPES}
      companyId={companyId}
      onCompanyChange={vi.fn()}
      busy={false}
      onSearch={onSearch}
    />,
  );
  return onSearch;
}

describe('detectType (AC-17-04 mirror)', () => {
  it('picks the longest prefix, else delivery order', () => {
    expect(detectType(TYPES, 'grn-0012')?.key).toBe('goods_receive_note');
    expect(detectType(TYPES, 'PS202610-0004')?.key).toBe('delivery_order');
    expect(detectType(TYPES, 'ZZ-1')?.key).toBe('delivery_order');
  });
});

describe('DocSearchForm', () => {
  it('submits the trimmed number with the detected type', () => {
    const onSearch = renderForm();
    fireEvent.change(screen.getByLabelText('Document number *'), { target: { value: '  PS202610-0004 ' } });
    fireEvent.click(screen.getByRole('button', { name: /find/i }));
    expect(onSearch).toHaveBeenCalledWith({
      companyId: 'c1', docNo: 'PS202610-0004', docType: 'delivery_order', aroundDay: null,
    });
  });

  it('warns and blocks Find when the company has no connection for the type', () => {
    renderForm();
    fireEvent.change(screen.getByLabelText('Document number *'), { target: { value: 'GRN-0001' } });
    expect(screen.getByTestId('ac-find-not-connected')).toHaveTextContent(
      'This company has no AutoCount connection for goods received notes yet.',
    );
    expect(screen.getByRole('button', { name: /find/i })).toBeDisabled();
  });

  it('keeps Find disabled without a company or number', () => {
    renderForm(vi.fn(), null);
    expect(screen.getByRole('button', { name: /find/i })).toBeDisabled();
  });
});
