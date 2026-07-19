import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { Product } from '@/types/ideation';
import { IdeaCaptureDialog } from './idea-capture-dialog';

const products: Product[] = [
  { id: 'prod-1', name: 'Sorento CRM', kind: 'software', productDomainBase: null },
  { id: 'prod-2', name: 'EcoHub', kind: 'software', productDomainBase: null },
];

describe('IdeaCaptureDialog (idea form)', () => {
  it('renders the segregated capture form fields', () => {
    render(<IdeaCaptureDialog products={products} onClose={vi.fn()} onCreate={vi.fn()} />);
    expect(screen.getByRole('heading', { name: /capture idea/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/problem statement/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/proposed solution/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^impact$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^department$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/raw notes/i)).toBeInTheDocument();
  });

  it('keeps submit disabled until a problem statement is entered (validation)', async () => {
    const user = userEvent.setup();
    render(<IdeaCaptureDialog products={products} onClose={vi.fn()} onCreate={vi.fn()} />);
    const submit = screen.getByRole('button', { name: /capture idea/i });
    expect(submit).toBeDisabled(); // product auto-selected but problem blank
    await user.type(screen.getByLabelText(/problem statement/i), 'Export orders to Excel');
    expect(submit).toBeEnabled();
  });

  it('submits the trimmed segregated input and closes on success (data path)', async () => {
    const user = userEvent.setup();
    const onCreate = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();
    render(<IdeaCaptureDialog products={products} onClose={onClose} onCreate={onCreate} />);
    await user.type(screen.getByLabelText(/problem statement/i), '  Export orders  ');
    await user.type(screen.getByLabelText(/proposed solution/i), '  Add a button  ');
    await user.type(screen.getByLabelText(/^impact$/i), '  Saves time  ');
    await user.type(screen.getByLabelText(/^department$/i), '  CS  ');
    await user.click(screen.getByRole('button', { name: /capture idea/i }));
    await waitFor(() =>
      expect(onCreate).toHaveBeenCalledWith(
        expect.objectContaining({
          productId: 'prod-1',
          problem: 'Export orders',
          proposedSolution: 'Add a button',
          impact: 'Saves time',
          department: 'CS',
        }),
      ),
    );
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it('surfaces the service error and stays open (error path)', async () => {
    const user = userEvent.setup();
    const onCreate = vi.fn().mockRejectedValue(new Error('in-app create is not available yet'));
    const onClose = vi.fn();
    render(<IdeaCaptureDialog products={products} onClose={onClose} onCreate={onCreate} />);
    await user.type(screen.getByLabelText(/problem statement/i), 'Export orders');
    await user.click(screen.getByRole('button', { name: /capture idea/i }));
    expect(await screen.findByText(/not available yet/i)).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });
});
