/**
 * AC-DLA-56 (T7) - the job detail's "Failed assets" table migrated off the
 * raw @/components/ui/table primitive onto DataGrid + DataGridTable.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { FailedAssetsCard } from './failed-assets-card';

describe('FailedAssetsCard (AC-DLA-56)', () => {
  it('renders a DataGrid with the key + reason columns for every failure', () => {
    render(
      <FailedAssetsCard
        failures={[
          { key: 'conn:a:media/1.png', reason: 'source object missing' },
          { key: 'conn:a:media/2.png', reason: 'checksum mismatch' },
        ]}
      />,
    );
    expect(screen.getByText('Failed assets (2)')).toBeInTheDocument();
    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Key' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Reason' })).toBeInTheDocument();
    expect(screen.getByText('conn:a:media/1.png')).toBeInTheDocument();
    expect(screen.getByText('source object missing')).toBeInTheDocument();
    expect(screen.getByText('checksum mismatch')).toBeInTheDocument();
  });

  it('renders the empty grid state for zero failures', () => {
    render(<FailedAssetsCard failures={[]} />);
    expect(screen.getByText('Failed assets (0)')).toBeInTheDocument();
  });
});
