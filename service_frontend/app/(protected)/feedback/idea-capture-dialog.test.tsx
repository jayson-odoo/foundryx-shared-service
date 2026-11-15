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
    // Plan 20 card fields; the legacy three are gone from the UI.
    expect(screen.getByLabelText(/^title$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/business problem/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/desired outcome/i)).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Use case 1' })).toBeInTheDocument();
    expect(screen.getByLabelText(/current workaround/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/original message/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/proposed solution/i)).toBeNull();
    expect(screen.queryByLabelText(/^impact$/i)).toBeNull();
    expect(screen.queryByLabelText(/^department$/i)).toBeNull();
  });

  it('keeps submit disabled until a problem statement is entered (validation)', async () => {
    const user = userEvent.setup();
    render(<IdeaCaptureDialog products={products} onClose={vi.fn()} onCreate={vi.fn()} />);
    const submit = screen.getByRole('button', { name: /capture idea/i });
    expect(submit).toBeDisabled(); // product auto-selected but problem blank
    await user.type(screen.getByLabelText(/business problem/i), 'Export orders to Excel');
    expect(submit).toBeEnabled();
  });

  it('submits the trimmed segregated input and closes on success (data path)', async () => {
    const user = userEvent.setup();
    const onCreate = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();
    render(<IdeaCaptureDialog products={products} onClose={onClose} onCreate={onCreate} />);
    await user.type(screen.getByLabelText(/business problem/i), '  Export orders  ');
    await user.type(screen.getByLabelText(/^title$/i), '  Excel export  ');
    await user.type(screen.getByLabelText(/desired outcome/i), '  Self-serve export  ');
    await user.type(screen.getByRole('textbox', { name: 'Use case 1' }), 'Monthly report');
    await user.type(screen.getByLabelText(/current workaround/i), '  Copy-paste  ');
    await user.click(screen.getByRole('button', { name: /capture idea/i }));
    await waitFor(() =>
      expect(onCreate).toHaveBeenCalledWith(
        expect.objectContaining({
          productId: 'prod-1',
          problem: 'Export orders',
          title: 'Excel export',
          desiredOutcome: 'Self-serve export',
          useCases: ['Monthly report'],
          currentWorkaround: 'Copy-paste',
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
    await user.type(screen.getByLabelText(/business problem/i), 'Export orders');
    await user.click(screen.getByRole('button', { name: /capture idea/i }));
    expect(await screen.findByText(/not available yet/i)).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });
});
