import { describe, expect, it, vi, beforeEach } from 'vitest';
import { useState } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { CreateHubDialog } from './create-hub-dialog';

const createHub = vi.fn();
vi.mock('@/services/hub-connector-service', () => ({
  hubConnectorService: { createHub: (...a: unknown[]) => createHub(...a) },
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function Harness({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(true);
  return <CreateHubDialog open={open} onOpenChange={setOpen} onCreated={onCreated} />;
}

beforeEach(() => {
  vi.clearAllMocks();
  createHub.mockResolvedValue({ hub: { id: 'h1' }, signingSecret: 'whsec_secret_value' });
});

describe('CreateHubDialog', () => {
  it('needs all three fields, then shows the signing secret once', async () => {
    const onCreated = vi.fn();
    render(<Harness onCreated={onCreated} />);
    expect(screen.getByRole('button', { name: 'Create' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Name *'), { target: { value: ' Partner Hub ' } });
    fireEvent.change(screen.getByLabelText('Code *'), { target: { value: 'partner' } });
    fireEvent.change(screen.getByLabelText('Receiver URL *'), { target: { value: 'https://hub.example.com/x' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(screen.getByLabelText('Signing secret')).toHaveValue('whsec_secret_value'));
    expect(createHub).toHaveBeenCalledWith({
      name: 'Partner Hub',
      code: 'partner',
      callbackUrl: 'https://hub.example.com/x',
    });
    expect(onCreated).toHaveBeenCalledTimes(1);
  });
});
