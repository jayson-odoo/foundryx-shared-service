import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { ShareDialog } from './share-dialog';
import type { ShareRow } from '@/types/documents';

const ensureShare = vi.fn();
const updateShare = vi.fn();
const listShareUsers = vi.fn();

vi.mock('@/services/document-service', () => ({
  documentService: {
    ensureShare: (...a: unknown[]) => ensureShare(...a),
    updateShare: (...a: unknown[]) => updateShare(...a),
    listShareUsers: (...a: unknown[]) => listShareUsers(...a),
  },
}));

const TARGET = { kind: 'folder' as const, id: 'fld-1', name: 'Quotations' };

const baseShare: ShareRow = {
  id: 's-1',
  targetKind: 'folder',
  targetId: 'fld-1',
  targetName: 'Quotations',
  generalAccess: 'restricted',
  capability: 'view',
  token: 'tok123',
  url: 'http://localhost:8001/public/documents/tok123',
  expiresAt: null,
  isExpired: false,
  hasPassword: false,
  maxUploads: null,
  maxTotalMb: null,
  isDisabled: false,
  people: [],
  createdAt: '2026-06-13T00:00:00Z',
};

beforeEach(() => {
  vi.clearAllMocks();
  ensureShare.mockResolvedValue({ ...baseShare });
  updateShare.mockResolvedValue({ ...baseShare });
  listShareUsers.mockResolvedValue([{ id: 'u-1', name: 'Ada Lovelace', email: 'ada@example.com' }]);
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
    configurable: true,
  });
});

describe('ShareDialog (Google model)', () => {
  it('ensures the stable link on open and shows one copyable URL', async () => {
    render(<ShareDialog target={TARGET} ceiling="edit" canManage onClose={() => {}} />);
    await waitFor(() => expect(ensureShare).toHaveBeenCalledWith('folder', 'fld-1'));
    const input = await screen.findByTestId('share-url');
    expect((input as HTMLInputElement).value).toContain('/public/documents/tok123');
    expect(screen.getByTestId('copy-link')).toBeInTheDocument();
  });

  it('annotates when public sharing is off (Public not offered)', async () => {
    render(<ShareDialog target={TARGET} ceiling="off" canManage onClose={() => {}} />);
    await screen.findByTestId('share-url');
    expect(screen.getByText(/Public links are turned off/i)).toBeInTheDocument();
  });

  it('renders the People + General access sections', async () => {
    render(<ShareDialog target={TARGET} ceiling="view" canManage onClose={() => {}} />);
    await screen.findByTestId('share-url');
    expect(screen.getByText('People with access')).toBeInTheDocument();
    expect(screen.getByText('General access')).toBeInTheDocument();
  });
});
