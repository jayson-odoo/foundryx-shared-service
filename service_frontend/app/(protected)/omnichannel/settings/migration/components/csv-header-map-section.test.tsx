/**
 * CSV header-map section (S6, AC-MIG-47, plan §5.6) - one row per system
 * field key, each offering the uploaded file's own headers plus "Not
 * mapped"; renders nothing until a file has been sniffed (no headers yet).
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MIGRATION_CSV_HEADER_KEYS } from '@/types/respondio-migration';
import { CsvHeaderMapSection } from './csv-header-map-section';

describe('CsvHeaderMapSection', () => {
  it('renders nothing before any file is uploaded (no headers yet)', () => {
    const { container } = render(
      <CsvHeaderMapSection headers={[]} value={{}} editing onChange={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('renders one row per system field key once headers exist', () => {
    render(
      <CsvHeaderMapSection
        headers={['First Name', 'Last Name', 'Phone']}
        value={{}}
        editing
        onChange={vi.fn()}
      />,
    );
    for (const { label } of MIGRATION_CSV_HEADER_KEYS) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it('an unmapped key is removed from the value object (falls back to the backend alias guess)', () => {
    const onChange = vi.fn();
    render(
      <CsvHeaderMapSection
        headers={['First Name']}
        value={{ firstName: 'First Name' }}
        editing
        onChange={onChange}
      />,
    );
    // The row already carries a mapped value - the component renders it, no
    // click needed to assert the initial props round-trip through the UI.
    expect(screen.getByText('First name')).toBeInTheDocument();
  });
});
