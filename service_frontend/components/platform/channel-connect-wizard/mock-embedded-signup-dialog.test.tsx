import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { MockEmbeddedSignupDialog } from './mock-embedded-signup-dialog';

/** Lane FEEDBACK-COMMENT-PHONE-LIKE-PORTAL: the simulated register step uses
 * the ONE shared SS phone input. Every number here is made up. */
describe('MockEmbeddedSignupDialog register step', () => {
  async function openRegister() {
    const onAuthorizeWaba = vi.fn();
    render(<MockEmbeddedSignupDialog open busy={false} onAuthorizeWaba={onAuthorizeWaba} onCancel={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: /register a different number/i }));
    return onAuthorizeWaba;
  }

  it('shows the shared phone input (Malaysia flag, +60, CRM placeholder)', async () => {
    await openRegister();
    expect(screen.getByRole('button', { name: 'Country: Malaysia (+60)' })).toBeInTheDocument();
    expect(screen.getByLabelText('Phone number')).toHaveAttribute('placeholder', '12-345 6789');
  });

  it('authorizes with the E.164 number', async () => {
    const onAuthorizeWaba = await openRegister();
    await userEvent.type(screen.getByLabelText('Business display name'), 'Test Desk');
    await userEvent.type(screen.getByLabelText('Phone number'), '012-345 0002');
    await userEvent.click(screen.getByRole('button', { name: 'Authorize' }));
    expect(onAuthorizeWaba).toHaveBeenCalledWith(
      expect.objectContaining({ displayPhoneNumber: '+60123450002', wabaId: 'waba-new-60123450002' }),
    );
  });

  it('keeps Authorize disabled while the number is incomplete', async () => {
    await openRegister();
    await userEvent.type(screen.getByLabelText('Business display name'), 'Test Desk');
    await userEvent.type(screen.getByLabelText('Phone number'), '0123');
    expect(screen.getByRole('button', { name: 'Authorize' })).toBeDisabled();
  });
});
