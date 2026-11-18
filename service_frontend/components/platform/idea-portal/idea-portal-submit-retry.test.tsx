import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api-client';

const push = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }), usePathname: () => '/', useParams: () => ({}) }));
const svc = vi.hoisted(() => ({ submit: vi.fn(), products: vi.fn(), uploadAttachment: vi.fn() }));
vi.mock('@/services/idea-portal-service', () => ({ ideaPortalService: svc }));
vi.mock('@/hooks/use-idea-portal', async () => {
  const actual = await vi.importActual<typeof import('@/hooks/use-idea-portal')>('@/hooks/use-idea-portal');
  return {
    ...actual,
    useIdeaPortal: () => ({
      mode: 'portal',
      paths: actual.PORTAL_PATHS,
      principal: { kind: 'crm', name: 'A', role: 'Staff', productId: 'p1', canManage: false },
      signOut: vi.fn(),
    }),
  };
});

import { SubmitIdeaForm } from './submit-idea-form';

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:x'), revokeObjectURL: vi.fn() }));
  svc.products.mockResolvedValue([{ id: 'p1', name: 'P' }]);
  svc.submit.mockResolvedValue({ id: 'new1' });
});

async function submitWithBadFile(container: HTMLElement) {
  svc.uploadAttachment.mockRejectedValue(new ApiError('too big', 413));
  await userEvent.type(screen.getByLabelText(/^Title/), 'T');
  await userEvent.type(screen.getByLabelText(/Business problem/), 'P');
  await userEvent.upload(container.querySelector('input[type="file"]') as HTMLInputElement, new File(['x'], 'huge.png', { type: 'image/png' }));
  await userEvent.click(screen.getByRole('button', { name: 'Submit' }));
  await screen.findByText('huge.png is too large (max 25 MB)');
}

describe('SubmitIdeaForm failed upload', () => {
  it('Open feedback goes to the created item', async () => {
    const { container } = render(<SubmitIdeaForm />);
    await submitWithBadFile(container);
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Open feedback' }));
    expect(push).toHaveBeenCalledWith(expect.stringContaining('new1'));
  });

  it('dropping the last failed file opens the created item', async () => {
    const { container } = render(<SubmitIdeaForm />);
    await submitWithBadFile(container);
    await userEvent.click(screen.getByRole('button', { name: 'Remove huge.png' }));
    await waitFor(() => expect(push).toHaveBeenCalledWith(expect.stringContaining('new1')));
  });
});
