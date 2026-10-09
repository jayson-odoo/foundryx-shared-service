import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { AutocountDocumentPrerequisite } from '@/types/autocount';

// Terminology drives the labels (AC-01-20): a tenant rename must carry through.
const overrides: Record<string, { singular: string; plural: string }> = {
  customer: { singular: 'Client', plural: 'Clients' },
};
function humanize(key: string) {
  return key.split('_').map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(' ');
}
vi.mock('@/hooks/use-terminology', () => ({
  useTerminology: () => ({
    ready: true,
    label: (k: string) => overrides[k]?.singular ?? humanize(k),
    labelPlural: (k: string) => overrides[k]?.plural ?? `${humanize(k)}s`,
    t: (k: string, n: number) => (n === 1 ? humanize(k) : `${humanize(k)}s`),
    refetch: vi.fn(),
  }),
}));

const { DocumentPrerequisiteCard } = await import('./document-prerequisite-card');

function line(over: Partial<AutocountDocumentPrerequisite> = {}): AutocountDocumentPrerequisite {
  return { entityType: 'sales_order', missing: [], inactive: [], ...over };
}

describe('DocumentPrerequisiteCard (plan sprint-5/01, AC-01-20)', () => {
  it('renders nothing when no document entity is configured', () => {
    const { container } = render(<DocumentPrerequisiteCard prerequisites={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing when every prerequisite is active', () => {
    const { container } = render(
      <DocumentPrerequisiteCard
        prerequisites={[line(), line({ entityType: 'purchase_order' })]}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('names ONLY the missing/inactive masters, with terminology labels, one line per document', () => {
    render(
      <DocumentPrerequisiteCard
        prerequisites={[
          line({ entityType: 'sales_order', missing: [], inactive: ['product'] }),
          line({ entityType: 'purchase_order', missing: ['supplier'], inactive: ['product'] }),
        ]}
        onAdd={vi.fn()}
      />,
    );
    expect(screen.getByTestId('document-prerequisites')).toBeInTheDocument();
    expect(screen.getByTestId('prerequisite-sales_order')).toHaveTextContent(
      'Sales Orders will stay retryable until Products is active.',
    );
    expect(screen.getByTestId('prerequisite-purchase_order')).toHaveTextContent(
      'Purchase Orders will stay retryable until Suppliers and Products are active.',
    );
    // The active master (customer) is never named.
    expect(screen.getByTestId('prerequisite-sales_order')).not.toHaveTextContent('Client');
  });

  it('bolds the blocking masters and uses the tenant\'s renamed label', () => {
    render(
      <DocumentPrerequisiteCard
        prerequisites={[line({ missing: ['customer'], inactive: ['product'] })]}
      />,
    );
    const strong = screen.getAllByText((_, el) => el?.tagName === 'STRONG' && Boolean(el.textContent));
    expect(strong.map((s) => s.textContent)).toEqual(['Clients', 'Products']);
  });

  it('offers an Add affordance for each MISSING master only, routing that entity', () => {
    const onAdd = vi.fn();
    render(
      <DocumentPrerequisiteCard
        prerequisites={[line({ entityType: 'purchase_order', missing: ['supplier'], inactive: ['product'] })]}
        onAdd={onAdd}
      />,
    );
    expect(screen.queryByTestId('add-prerequisite-product')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('add-prerequisite-supplier'));
    expect(onAdd).toHaveBeenCalledWith('supplier');
    expect(screen.getByTestId('add-prerequisite-supplier')).toHaveTextContent('Add Supplier');
  });

  it('withholds the Add affordance without manage permission (no onAdd)', () => {
    render(
      <DocumentPrerequisiteCard prerequisites={[line({ missing: ['customer'] })]} />,
    );
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.getByTestId('prerequisite-sales_order')).toHaveTextContent('Clients is active.');
  });

  it('skips a fully-active document line while keeping the blocked one', () => {
    render(
      <DocumentPrerequisiteCard
        prerequisites={[line(), line({ entityType: 'purchase_order', missing: ['supplier'] })]}
      />,
    );
    expect(screen.queryByTestId('prerequisite-sales_order')).not.toBeInTheDocument();
    expect(screen.getByTestId('prerequisite-purchase_order')).toBeInTheDocument();
  });
});
