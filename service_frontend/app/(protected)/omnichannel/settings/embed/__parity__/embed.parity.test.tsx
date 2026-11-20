/**
 * Switch-off parity for the Embed access page (Foundryx UIUX slice W2-WS):
 * the not-enabled state, the Setup tab with and without a secret, the rotate
 * confirm, the secret shown once after rotating, and the Allowed origins
 * editor, rendered with the switch OFF. Recorded on the code as it was before
 * the slice; a change that needs one of these snapshots updated is wrong by
 * definition (fix the code, never the snapshot).
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { parityHtml } from '@/components/fx/__parity__/parity-utils';
import type { EmbedConfig } from '@/services/embed-config-service';

const store: EmbedConfig = {
  connectionId: 'conn-embed-1',
  allowedOrigins: ['https://crm.acme.com'],
  hasSecret: true,
  host: 'https://api.example.com',
  workspaces: [
    { id: 'ws-general', name: 'General' },
    { id: 'ws-sales', name: 'Sales' },
  ],
};
const get = vi.fn();
const rotateSecret = vi.fn();
const setOrigins = vi.fn();
vi.mock('@/services/embed-config-service', () => ({
  embedConfigService: {
    get: (...a: unknown[]) => get(...a),
    enable: vi.fn(),
    rotateSecret: (...a: unknown[]) => rotateSecret(...a),
    setOrigins: (...a: unknown[]) => setOrigins(...a),
  },
}));

import { EmbedAccessPanel } from '../embed-access-panel';
import { OriginsEditor } from '../origins-editor';

function stable(root: Element): string {
  const seen = new Map<string, string>();
  return parityHtml(root).replace(/_r_[0-9a-z]+_/g, (id) => {
    let name = seen.get(id);
    if (!name) {
      name = `_rid${seen.size}_`;
      seen.set(id, name);
    }
    return name;
  });
}

beforeEach(() => {
  get.mockReset();
  rotateSecret.mockReset();
  rotateSecret.mockResolvedValue({ embedSecret: 'emb_secret_shown_once_abc123' });
  get.mockImplementation(async () => ({ ...store }));
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
    configurable: true,
  });
});

describe('parity (switch off): embed access', () => {
  it('not enabled yet', async () => {
    get.mockImplementation(async () => ({ ...store, connectionId: null }));
    const { container } = render(<EmbedAccessPanel />);
    await screen.findByRole('button', { name: 'Enable embed access' });
    expect(stable(container)).toMatchSnapshot();
  });

  it('setup tab with a secret set', async () => {
    const { container } = render(<EmbedAccessPanel />);
    await screen.findByText('Connection id');
    expect(stable(container)).toMatchSnapshot();
  });

  it('setup tab with no secret', async () => {
    get.mockImplementation(async () => ({ ...store, hasSecret: false }));
    const { container } = render(<EmbedAccessPanel />);
    await screen.findByRole('button', { name: 'Generate secret' });
    expect(stable(container)).toMatchSnapshot();
  });

  it('rotate confirm open', async () => {
    render(<EmbedAccessPanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'Rotate secret' }));
    await screen.findByText('Rotate the embed secret?');
    expect(stable(document.body)).toMatchSnapshot();
  });

  it('the new secret shown once after rotating', async () => {
    const { container } = render(<EmbedAccessPanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'Rotate secret' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Rotate' }));
    await waitFor(() => expect(screen.getByLabelText('embed secret')).toHaveValue('emb_secret_shown_once_abc123'));
    expect(stable(container)).toMatchSnapshot();
  });

  it('allowed origins editor, untouched and changed', () => {
    const { container } = render(<OriginsEditor origins={['https://crm.acme.com']} onSave={vi.fn()} />);
    expect(stable(container)).toMatchSnapshot();
    fireEvent.change(screen.getByLabelText('New allowed origin'), { target: { value: 'https://app.acme.com' } });
    fireEvent.click(screen.getByRole('button', { name: /Add/ }));
    expect(stable(container)).toMatchSnapshot();
  });
});
