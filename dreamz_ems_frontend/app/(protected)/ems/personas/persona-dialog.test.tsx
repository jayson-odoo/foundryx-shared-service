import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Persona } from '@/types/persona';
import { PersonaDialog } from './persona-dialog';

// ── Service: spy on create/update/setPermissions to assert the save shape. ──
const { create, update, setPermissions, getPermissions, portalPermissions } =
  vi.hoisted(() => ({
    create: vi.fn(),
    update: vi.fn(),
    setPermissions: vi.fn(),
    getPermissions: vi.fn(),
    portalPermissions: vi.fn(),
  }));
vi.mock('@/services/persona-service', () => ({
  personaService: { create, update, setPermissions, getPermissions, portalPermissions },
}));

const SYSTEM_PERSONA: Persona = {
  id: 'p-reviewer',
  key: 'reviewer',
  label: 'Reviewer',
  description: 'Peer reviewer',
  isSystem: true,
  sortOrder: 20,
  createdAt: '2026-06-21T00:00:00Z',
};

describe('PersonaDialog', () => {
  beforeEach(() => {
    create.mockReset().mockResolvedValue({});
    update.mockReset().mockResolvedValue({});
    setPermissions.mockReset().mockResolvedValue([]);
    getPermissions.mockReset().mockResolvedValue([]);
    portalPermissions.mockReset().mockResolvedValue([
      { key: 'my_reviews.read', label: 'My Reviews (portal)', description: '' },
      { key: 'decisions.read', label: 'Decisions (portal)', description: '' },
    ]);
  });

  it('disables Create until a key and label are entered (label required)', async () => {
    render(<PersonaDialog item={null} onClose={vi.fn()} onSaved={vi.fn()} />);
    const user = userEvent.setup();

    const createBtn = screen.getByRole('button', { name: /create/i });
    expect(createBtn).toBeDisabled();

    await user.type(screen.getByLabelText(/key/i), 'sponsor');
    // Key alone is not enough — label is required too.
    expect(createBtn).toBeDisabled();

    await user.type(screen.getByLabelText(/label/i), 'Sponsor');
    expect(createBtn).toBeEnabled();
  });

  it('creates a persona with the entered key + label', async () => {
    const onSaved = vi.fn();
    render(<PersonaDialog item={null} onClose={vi.fn()} onSaved={onSaved} />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/key/i), 'sponsor');
    await user.type(screen.getByLabelText(/label/i), 'Sponsor');
    await user.click(screen.getByRole('button', { name: /create/i }));

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith(
        expect.objectContaining({ key: 'sponsor', label: 'Sponsor' }),
      ),
    );
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });

  it('locks the key for a system persona (read-only) but keeps the label editable', () => {
    render(
      <PersonaDialog item={SYSTEM_PERSONA} onClose={vi.fn()} onSaved={vi.fn()} />,
    );
    const keyInput = screen.getByLabelText(/key/i) as HTMLInputElement;
    expect(keyInput).toHaveAttribute('readonly');
    expect(keyInput).toBeDisabled();
    expect(screen.getByLabelText(/^label/i)).toBeEnabled();
  });

  it('saving an edit never sends a system persona key, and persists grants', async () => {
    const onSaved = vi.fn();
    render(
      <PersonaDialog item={SYSTEM_PERSONA} onClose={vi.fn()} onSaved={onSaved} />,
    );
    const user = userEvent.setup();

    await user.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() =>
      expect(update).toHaveBeenCalledWith(
        'p-reviewer',
        expect.objectContaining({ key: undefined, label: 'Reviewer' }),
      ),
    );
    // The grant editor is saved as a keys[] shape via PUT.
    await waitFor(() => expect(setPermissions).toHaveBeenCalled());
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });
});
