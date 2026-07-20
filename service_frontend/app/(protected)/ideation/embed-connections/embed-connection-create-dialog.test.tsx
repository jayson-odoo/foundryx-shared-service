import { describe, expect, it, vi, beforeEach } from 'vitest';
import { useState } from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import type { Product } from '@/types/ideation';
import { EmbedConnectionCreateDialog } from './embed-connection-create-dialog';

const create = vi.fn();

vi.mock('@/services/embed-connection-service', () => ({
  embedConnectionService: {
    create: (...a: unknown[]) => create(...a),
    list: vi.fn(),
    rotate: vi.fn(),
    setActive: vi.fn(),
    remove: vi.fn(),
  },
}));

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const PRODUCTS: Product[] = [
  { id: 'prod-1', name: 'Sorento CRM', kind: 'software', productDomainBase: null },
];

const TYPED_SECRET = 'my-typed-secret-1234';

beforeEach(() => {
  vi.clearAllMocks();
  create.mockResolvedValue({
    connectionId: 'sorento-ideation',
    tenantId: 'default',
    allowedOrigins: [],
    productId: null,
    isActive: true,
    hasSecret: true,
    createdAt: '2026-07-18T00:00:00Z',
    updatedAt: '2026-07-18T00:00:00Z',
  });
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
    configurable: true,
  });
});

/** Controlled harness so we can toggle `open` (to test clear-on-close). */
function Harness() {
  const [open, setOpen] = useState(true);
  return (
    <>
      <button onClick={() => setOpen(true)}>reopen</button>
      <EmbedConnectionCreateDialog
        open={open}
        onOpenChange={setOpen}
        products={PRODUCTS}
        onCreated={() => {}}
      />
    </>
  );
}

describe('EmbedConnectionCreateDialog (PLAN-ideation-embed-sso §7)', () => {
  it('renders the create form fields', () => {
    render(<Harness />);
    expect(screen.getByLabelText(/connection id/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/signing secret/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /generate/i })).toBeInTheDocument();
  });

  it('keeps Create disabled until a connection id and an ≥8-char secret are present', () => {
    render(<Harness />);
    const createBtn = screen.getByRole('button', { name: /create connection/i });
    expect(createBtn).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/connection id/i), {
      target: { value: 'sorento-ideation' },
    });
    // A too-short secret keeps it disabled.
    fireEvent.change(screen.getByLabelText(/signing secret/i), { target: { value: 'short' } });
    expect(createBtn).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/signing secret/i), { target: { value: TYPED_SECRET } });
    expect(createBtn).not.toBeDisabled();
  });

  it('Generate fills a strong (≥8-char) secret and enables Create', () => {
    render(<Harness />);
    fireEvent.change(screen.getByLabelText(/connection id/i), {
      target: { value: 'sorento-ideation' },
    });
    fireEvent.click(screen.getByRole('button', { name: /generate/i }));
    const secretInput = screen.getByLabelText(/signing secret/i) as HTMLInputElement;
    expect(secretInput.value.length).toBeGreaterThanOrEqual(8);
    expect(screen.getByRole('button', { name: /create connection/i })).not.toBeDisabled();
  });

  it('reveals the secret ONCE after create with a copy affordance + "won\'t be shown again"', async () => {
    render(<Harness />);
    fireEvent.change(screen.getByLabelText(/connection id/i), {
      target: { value: 'sorento-ideation' },
    });
    fireEvent.change(screen.getByLabelText(/signing secret/i), { target: { value: TYPED_SECRET } });
    fireEvent.click(screen.getByRole('button', { name: /create connection/i }));

    await waitFor(() => {
      expect(screen.getByDisplayValue(TYPED_SECRET)).toBeInTheDocument();
    });
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({ connectionId: 'sorento-ideation', signingSecret: TYPED_SECRET }),
    );
    expect(screen.getByText(/won.t be shown again/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /copy signing secret/i })).toBeInTheDocument();
  });

  it('copy writes the secret to the clipboard', async () => {
    render(<Harness />);
    fireEvent.change(screen.getByLabelText(/connection id/i), {
      target: { value: 'sorento-ideation' },
    });
    fireEvent.change(screen.getByLabelText(/signing secret/i), { target: { value: TYPED_SECRET } });
    fireEvent.click(screen.getByRole('button', { name: /create connection/i }));
    await waitFor(() => screen.getByDisplayValue(TYPED_SECRET));

    fireEvent.click(screen.getByRole('button', { name: /copy signing secret/i }));
    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(TYPED_SECRET);
    });
  });

  it('closing clears the revealed secret (never persisted)', async () => {
    render(<Harness />);
    fireEvent.change(screen.getByLabelText(/connection id/i), {
      target: { value: 'sorento-ideation' },
    });
    fireEvent.change(screen.getByLabelText(/signing secret/i), { target: { value: TYPED_SECRET } });
    fireEvent.click(screen.getByRole('button', { name: /create connection/i }));
    await waitFor(() => screen.getByDisplayValue(TYPED_SECRET));

    fireEvent.click(screen.getByRole('button', { name: /done/i }));
    await waitFor(() => {
      expect(screen.queryByDisplayValue(TYPED_SECRET)).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: /reopen/i }));
    await waitFor(() => {
      expect(screen.getByLabelText(/connection id/i)).toHaveValue('');
    });
    expect(screen.queryByDisplayValue(TYPED_SECRET)).not.toBeInTheDocument();
  });
});
