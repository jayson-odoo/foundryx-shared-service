import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PortalInviteButton } from './portal-invite-button';

// ── Service spy: assert sendPortalInvite is called with the profile id (+ grant). ──
const { sendPortalInvite } = vi.hoisted(() => ({ sendPortalInvite: vi.fn() }));
vi.mock('@/services/persona-service', () => ({
  personaService: { sendPortalInvite },
}));

// useCan → grant personas.manage by default (the button is gated on it).
const { can } = vi.hoisted(() => ({ can: vi.fn(() => true) }));
vi.mock('@/hooks/use-can', () => ({ useCan: () => ({ can }) }));

const { success, error } = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock('sonner', () => ({ toast: { success, error } }));

describe('PortalInviteButton', () => {
  beforeEach(() => {
    sendPortalInvite.mockReset().mockResolvedValue({ sent: true, email: 'p@e2e.com' });
    can.mockReset().mockReturnValue(true);
    success.mockReset();
    error.mockReset();
  });

  it('calls the service with the profile id and toasts success', async () => {
    render(<PortalInviteButton profileId="prof-1" email="p@e2e.com" />);
    const user = userEvent.setup();

    await user.click(screen.getByRole('button', { name: /send portal invite/i }));

    await waitFor(() =>
      expect(sendPortalInvite).toHaveBeenCalledWith('prof-1', undefined),
    );
    await waitFor(() =>
      expect(success).toHaveBeenCalledWith('Portal invite sent to p@e2e.com.'),
    );
  });

  it('passes an optional persona grant payload through', async () => {
    const grant = { personaKey: 'participant', scopeType: 'project', scopeId: 'ev-1' };
    render(<PortalInviteButton profileId="prof-2" email="p@e2e.com" grant={grant} />);
    const user = userEvent.setup();

    await user.click(screen.getByRole('button', { name: /send portal invite/i }));

    await waitFor(() =>
      expect(sendPortalInvite).toHaveBeenCalledWith('prof-2', grant),
    );
  });

  it('is disabled when the profile has no email', () => {
    render(<PortalInviteButton profileId="prof-3" email="" />);
    expect(screen.getByRole('button', { name: /send portal invite/i })).toBeDisabled();
  });

  it('toasts the error message on failure', async () => {
    sendPortalInvite.mockRejectedValueOnce(new Error('Boom'));
    render(<PortalInviteButton profileId="prof-4" email="p@e2e.com" />);
    const user = userEvent.setup();

    await user.click(screen.getByRole('button', { name: /send portal invite/i }));

    await waitFor(() => expect(error).toHaveBeenCalledWith('Boom'));
  });

  it('renders nothing without personas.manage', () => {
    can.mockReturnValue(false);
    const { container } = render(
      <PortalInviteButton profileId="prof-5" email="p@e2e.com" />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
