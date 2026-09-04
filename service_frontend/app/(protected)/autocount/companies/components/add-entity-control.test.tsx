import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { AutocountEntityConfig } from '@/types/autocount';
import { AddEntityControl } from './add-entity-control';

function entity(over: Partial<AutocountEntityConfig> = {}): AutocountEntityConfig {
  return {
    id: 'e1',
    entityType: 'product_category',
    syncMode: 'SCHEDULED_REVIEW',
    sourceImpl: 'sql_db',
    recordCap: 200,
    initialLookbackDays: 30,
    enabled: true,
    lastSuccessAt: null,
    lastAttemptAt: null,
    watermarkAt: null,
    consecutiveFailures: 0,
    lastError: null,
    etlStatus: 'draft',
    ...over,
  };
}

const SEVEN = [
  'product_category', 'unit_of_measure', 'warehouse', 'product', 'sales_agent',
  'sales_order', 'purchase_order',
];

describe('AddEntityControl (plan 22 S4, AC-22-23)', () => {
  it('offers only the masters fan-out entities NOT already configured', async () => {
    render(
      <AddEntityControl
        entities={[entity({ entityType: 'product_category' })]}
        sourceKind="api"
        onAdd={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole('combobox', { name: 'Add entity' }));
    expect(await screen.findByRole('option', { name: 'Unit of measure' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Warehouse' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Product' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Sales agent' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Product category' })).not.toBeInTheDocument();
  });

  it('withholds Configure until an entity is picked, then calls onAdd with it', async () => {
    const onAdd = vi.fn();
    render(<AddEntityControl entities={[]} sourceKind="api" onAdd={onAdd} />);
    expect(screen.getByTestId('add-entity-configure')).toBeDisabled();
    fireEvent.click(screen.getByRole('combobox', { name: 'Add entity' }));
    fireEvent.click(await screen.findByRole('option', { name: 'Product' }));
    const button = screen.getByTestId('add-entity-configure');
    expect(button).toBeEnabled();
    fireEvent.click(button);
    expect(onAdd).toHaveBeenCalledWith('product');
  });

  it('offers the two document entities (plan 22 S5) alongside the masters', () => {
    render(<AddEntityControl entities={[]} sourceKind="api" onAdd={vi.fn()} />);
    expect(screen.getByRole('combobox')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('combobox'));
    expect(screen.getByText('Sales order')).toBeInTheDocument();
    expect(screen.getByText('Purchase order')).toBeInTheDocument();
  });

  it('renders nothing once every DB-source entity is already configured', () => {
    const all = SEVEN.map((entityType) => entity({ id: entityType, entityType }));
    const { container } = render(
      <AddEntityControl entities={all} sourceKind="api" onAdd={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe('AddEntityControl - company kind (plan sprint-5/01, AC-01-17)', () => {
  it('an API company keeps today\'s seven - customer/supplier are API-seeded, never added', () => {
    render(<AddEntityControl entities={[]} sourceKind="api" onAdd={vi.fn()} />);
    fireEvent.click(screen.getByRole('combobox', { name: 'Add entity' }));
    expect(screen.getAllByRole('option')).toHaveLength(7);
    expect(screen.queryByRole('option', { name: 'Customer' })).not.toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Supplier' })).not.toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Goods received note' })).not.toBeInTheDocument();
  });

  it('a DB company offers all ten sql_db entities incl. customer + supplier, never GRN', () => {
    render(<AddEntityControl entities={[]} sourceKind="db" onAdd={vi.fn()} />);
    fireEvent.click(screen.getByRole('combobox', { name: 'Add entity' }));
    const names = screen.getAllByRole('option').map((o) => o.textContent);
    expect(names).toHaveLength(10);
    expect(names).toEqual(
      expect.arrayContaining([
        'Customer', 'Supplier', 'Product category', 'Unit of measure', 'Warehouse',
        'Product', 'Sales agent', 'Sales order', 'Purchase order', 'Shipping order',
      ]),
    );
    expect(names).not.toContain('Goods received note');
  });

  it('a DB company\'s list drops the entities already configured', () => {
    render(
      <AddEntityControl
        entities={[entity({ entityType: 'customer' }), entity({ id: 'e2', entityType: 'sales_order' })]}
        sourceKind="db"
        onAdd={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole('combobox', { name: 'Add entity' }));
    const names = screen.getAllByRole('option').map((o) => o.textContent);
    expect(names).toHaveLength(8);
    expect(names).not.toContain('Customer');
    expect(names).not.toContain('Sales order');
    expect(names).toContain('Supplier');
  });
});
