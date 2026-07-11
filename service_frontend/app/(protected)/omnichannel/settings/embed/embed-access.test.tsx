import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { EmbedConfig } from '@/services/embed-config-service';
import { buildSnippet } from './snippet-card';

// ── service mock (vi.fn spies over an in-memory store) ───────────────────────
const store: EmbedConfig = {
  connectionId: 'conn-embed-1',
  allowedOrigins: [],
  hasSecret: false,
  host: 'https://foundryx.example',
  workspaces: [
    { id: 'ws-general', name: 'General' },
    { id: 'ws-sales', name: 'Sales' },
  ],
};

const get = vi.fn();
const enable = vi.fn();
const rotateSecret = vi.fn();
const setOrigins = vi.fn();

vi.mock('@/services/embed-config-service', () => ({
  embedConfigService: {
    get: (...a: unknown[]) => get(...a),
    enable: (...a: unknown[]) => enable(...a),
    rotateSecret: (...a: unknown[]) => rotateSecret(...a),
    setOrigins: (...a: unknown[]) => setOrigins(...a),
  },
}));

// Imported AFTER the mock so the hook binds the spied service.
import { EmbedAccessPanel } from './embed-access-panel';

beforeEach(() => {
  vi.clearAllMocks();
  store.connectionId = 'conn-embed-1';
  store.allowedOrigins = [];
  store.hasSecret = false;
  get.mockImplementation(async () => ({ ...store }));
  enable.mockImplementation(async () => {
    store.connectionId = 'conn-embed-1';
    return { ...store };
  });
  rotateSecret.mockImplementation(async () => {
    store.hasSecret = true;
    return { embedSecret: 'emb_secret_shown_once_abc123' };
  });
  setOrigins.mockImplementation(async (origins: string[]) => {
    store.allowedOrigins = origins;
    return { ...store };
  });
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
    configurable: true,
  });
});

describe('EmbedAccessPanel', () => {
  it('renders the connection id with a copy button', async () => {
    render(<EmbedAccessPanel />);
    expect(await screen.findByDisplayValue('conn-embed-1')).toBeInTheDocument();
    const copy = screen.getByRole('button', { name: /copy connection id/i });
    await userEvent.click(copy);
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('conn-embed-1');
  });

  it('shows the empty state + enables when there is no connection', async () => {
    store.connectionId = null;
    render(<EmbedAccessPanel />);
    const btn = await screen.findByRole('button', { name: /enable embed access/i });
    await userEvent.click(btn);
    expect(enable).toHaveBeenCalledTimes(1);
  });

  it('rotate reveals the secret exactly once', async () => {
    render(<EmbedAccessPanel />);
    await screen.findByDisplayValue('conn-embed-1');
    await userEvent.click(screen.getByRole('button', { name: /generate secret/i }));
    // Confirm dialog.
    const confirm = await screen.findByRole('button', { name: /^generate$/i });
    await userEvent.click(confirm);
    await waitFor(() => expect(rotateSecret).toHaveBeenCalledTimes(1));
    expect(await screen.findByDisplayValue('emb_secret_shown_once_abc123')).toBeInTheDocument();
    expect(screen.getByText(/won't be shown again/i)).toBeInTheDocument();
  });

  it('adds an origin and saves it through the service', async () => {
    render(<EmbedAccessPanel />);
    await screen.findByDisplayValue('conn-embed-1');
    const input = screen.getByLabelText(/new allowed origin/i);
    await userEvent.type(input, 'https://crm.acme.com');
    await userEvent.click(screen.getByRole('button', { name: /^add$/i }));
    expect(screen.getByText('https://crm.acme.com')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /save origins/i }));
    await waitFor(() =>
      expect(setOrigins).toHaveBeenCalledWith(['https://crm.acme.com']),
    );
  });

  it('removes a staged origin before saving', async () => {
    render(<EmbedAccessPanel />);
    await screen.findByDisplayValue('conn-embed-1');
    const input = screen.getByLabelText(/new allowed origin/i);
    await userEvent.type(input, 'https://crm.acme.com');
    await userEvent.click(screen.getByRole('button', { name: /^add$/i }));
    await userEvent.click(screen.getByRole('button', { name: /remove https:\/\/crm.acme.com/i }));
    expect(screen.queryByText('https://crm.acme.com')).not.toBeInTheDocument();
  });
});

describe('buildSnippet', () => {
  it('reflects the selected route', () => {
    expect(buildSnippet('https://foundryx.example', 'c1', 'thread', 'ws-1')).toContain(
      '/embed/omnichannel/thread?c=c1',
    );
    expect(buildSnippet('https://foundryx.example', 'c1', 'inbox', 'ws-1')).toContain(
      '/embed/omnichannel/inbox?c=c1',
    );
  });

  it('reflects the selected workspace and trims a trailing host slash', () => {
    const snippet = buildSnippet('https://foundryx.example/', 'c1', 'thread', 'ws-sales');
    expect(snippet).toContain('workspaceId for your assertion: ws-sales');
    expect(snippet).toContain('https://foundryx.example/embed/omnichannel/thread?c=c1');
  });
});
