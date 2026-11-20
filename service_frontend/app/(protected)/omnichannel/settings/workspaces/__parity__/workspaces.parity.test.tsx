/**
 * Switch-off parity for the Workspaces pages (Foundryx UIUX slice W2-WS,
 * build plan 1.3 and 4): the list, the API Keys tab, the mint dialog (name
 * and reveal steps) and the revoke dialog, rendered with the switch OFF.
 * Recorded on the code as it was before the slice; a change that needs one of
 * these snapshots updated is wrong by definition (fix the code, never the
 * snapshot). Generated ids are renamed in order of appearance.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { parityHtml } from '@/components/fx/__parity__/parity-utils';
import { SettingsProvider } from '@/providers/settings-provider';
import type { ApiKeyItem } from '@/types/api-keys';
import type { Workspace } from '@/types/omnichannel';
import WorkspacesPage from '../page';
import { ApiKeysTab } from '../components/workspace-api-keys-tab';
import { MintApiKeyDialog } from '../components/mint-api-key-dialog';
import { RevokeApiKeyDialog } from '../components/revoke-api-key-dialog';

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/omnichannel/settings/workspaces'),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { name: 'Demo Admin', permissions: [] } },
    status: 'authenticated',
  }),
}));
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>() }),
}));
vi.mock('@/components/common/require-permission', () => ({
  RequirePermission: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/services/preferences-service', () => ({
  preferencesService: { get: vi.fn().mockResolvedValue(null), save: vi.fn().mockResolvedValue(undefined) },
}));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));
vi.mock('@/providers/import-activity-provider', () => ({
  useImportActivity: () => ({ openImport: vi.fn() }),
}));
vi.mock('@/services/pending-actions-service', () => ({
  pendingActionsService: { park: vi.fn(), cancel: vi.fn(), current: vi.fn().mockResolvedValue({ pending: null }) },
}));

const ws = (over: Partial<Workspace>): Workspace => ({
  id: 'wsp-1',
  tenantId: 'ten-1',
  name: 'General',
  status: 'ACTIVE',
  channelCount: 2,
  memberCount: 5,
  isDefault: true,
  isTrashed: false,
  createdAt: '2026-11-01T02:00:00Z',
  updatedAt: '2026-11-01T02:00:00Z',
  ...over,
});
const WORKSPACES: Workspace[] = [
  ws({}),
  ws({ id: 'wsp-2', name: 'Sales', isDefault: false, status: 'INACTIVE', channelCount: 0, memberCount: 1 }),
];

vi.mock('@/services/workspace-service', () => ({
  workspaceService: {
    list: vi.fn(async () => ({ data: WORKSPACES, total: WORKSPACES.length, page: 0 })),
    exportCsv: vi.fn(async () => ''),
    get: vi.fn(),
    getAt: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    trash: vi.fn(),
    restore: vi.fn(),
  },
}));

const key = (over: Partial<ApiKeyItem>): ApiKeyItem => ({
  id: 'key-1',
  workspaceId: 'wsp-1',
  name: 'Production server',
  keyPrefix: 'abcd1234',
  maskedKey: 'fxw_live_abcd1234••••',
  status: 'ACTIVE',
  lastUsedAt: null,
  revokedAt: null,
  createdAt: '2026-11-01T02:00:00Z',
  webhookEndpointCount: 0,
  ...over,
});
const KEYS: ApiKeyItem[] = [
  key({}),
  key({ id: 'key-2', name: 'Order sync', keyPrefix: 'ffee0011', maskedKey: 'fxw_live_ffee0011••••', webhookEndpointCount: 3, lastUsedAt: '2026-11-10T03:00:00Z' }),
  key({ id: 'key-3', name: 'Old', status: 'REVOKED', revokedAt: '2026-11-05T00:00:00Z' }),
];
const FULL_KEY = 'fxw_live_abcd1234thisisthesecrettail';
const mint = vi.fn();
vi.mock('@/services/api-keys-service', () => ({
  apiKeysService: {
    list: vi.fn(async () => KEYS),
    mint: (...a: unknown[]) => mint(...a),
    revoke: vi.fn(),
  },
}));

/** Also masks React 19's `_r_N_` ids, in order of first appearance. */
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
  mint.mockReset();
  mint.mockResolvedValue({ key: KEYS[0], fullKey: FULL_KEY });
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
    configurable: true,
  });
});

describe('parity (switch off): Workspaces list', () => {
  it('list with rows, toolbar and New workspace', async () => {
    const { container } = render(
      <SettingsProvider>
        <WorkspacesPage />
      </SettingsProvider>,
    );
    await screen.findByText('Sales');
    expect(stable(container)).toMatchSnapshot();
  });
});

describe('parity (switch off): API Keys tab', () => {
  it('keys list inside the tab', async () => {
    const { container } = render(<ApiKeysTab workspaceId="wsp-1" creating={false} />);
    await screen.findByText('Order sync');
    expect(stable(container)).toMatchSnapshot();
  });

  it('while creating', () => {
    const { container } = render(<ApiKeysTab workspaceId={null} creating />);
    expect(stable(container)).toMatchSnapshot();
  });
});

describe('parity (switch off): mint dialog', () => {
  it('name step', () => {
    render(<MintApiKeyDialog workspaceId="wsp-1" open onOpenChange={vi.fn()} onMinted={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('Key name'), { target: { value: 'Production server' } });
    expect(stable(document.body)).toMatchSnapshot();
  });

  it('reveal step', async () => {
    render(<MintApiKeyDialog workspaceId="wsp-1" open onOpenChange={vi.fn()} onMinted={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('Key name'), { target: { value: 'Production server' } });
    fireEvent.click(screen.getByRole('button', { name: /Mint key/ }));
    await waitFor(() => expect(screen.getByLabelText('API key')).toHaveValue(FULL_KEY));
    expect(stable(document.body)).toMatchSnapshot();
  });
});

describe('parity (switch off): revoke dialog', () => {
  it('a key with endpoints', () => {
    render(<RevokeApiKeyDialog keyName="Order sync" endpointCount={3} onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(stable(document.body)).toMatchSnapshot();
  });
});
