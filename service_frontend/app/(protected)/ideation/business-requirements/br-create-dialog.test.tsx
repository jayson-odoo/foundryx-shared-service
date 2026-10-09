import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BrCreateDialog } from './br-create-dialog';

/**
 * Issue #90 W2 (AC-90-210). Coordinator ruling Q1: no BR template admin page
 * exists (BL-SS-278) - the dialog names the fix with NO link, and disables
 * Create. Reads `useBrTemplateStatus()` (new hook) so the dialog never lets a
 * user hit the 422 in the common case.
 */

const useBrTemplateStatus = vi.hoisted(() => vi.fn());
vi.mock('@/hooks/use-br-template-status', () => ({
  useBrTemplateStatus: () => useBrTemplateStatus(),
}));

const products = [{ id: 'prod-1', name: 'Sorento CRM', kind: 'software' as const }];

beforeEach(() => {
  useBrTemplateStatus.mockReset();
  useBrTemplateStatus.mockReturnValue({ active: true, loading: false });
});

describe('BrCreateDialog - AC-90-210 no active template', () => {
  it('renders an Alert and disables Create when the template is inactive', () => {
    useBrTemplateStatus.mockReturnValue({ active: false, loading: false });
    render(<BrCreateDialog products={products} onClose={vi.fn()} onCreate={vi.fn()} />);
    expect(
      screen.getByText(/no active requirement template/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/ask an administrator to restore the business requirement template/i),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /create draft/i })).toBeDisabled();
    // Q1: no template admin page exists yet - no link is rendered.
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('does not render the Alert and Create stays enabled when the template is active', () => {
    render(<BrCreateDialog products={products} onClose={vi.fn()} onCreate={vi.fn()} />);
    expect(screen.queryByText(/no active requirement template/i)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /create draft/i })).toBeEnabled();
  });

  it('renders the Alert after a create 422 carrying br_template_unavailable, even if the hook reported active', async () => {
    const { ApiError } = await import('@/lib/api-client');
    const onCreate = vi
      .fn()
      .mockRejectedValue(
        new ApiError('No active Business Requirement template is configured.', 422, undefined, {
          code: 'br_template_unavailable',
          message: 'No active Business Requirement template is configured.',
        }),
      );
    render(<BrCreateDialog products={products} onClose={vi.fn()} onCreate={onCreate} />);
    screen.getByRole('button', { name: /create draft/i }).click();
    await waitFor(() =>
      expect(screen.getByText(/no active requirement template/i)).toBeInTheDocument(),
    );
    expect(screen.getByRole('button', { name: /create draft/i })).toBeDisabled();
  });
});
