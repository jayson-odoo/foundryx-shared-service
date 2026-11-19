/**
 * Switch-off parity for the email log pages (Foundryx UIUX slice W3-LOGS,
 * build plan 1.3 and 4): the list, and one email's Overview and Body tab in
 * its three views, rendered with the switch OFF. Recorded on the code as it
 * was before the slice; a change that needs one of these snapshots updated
 * is wrong by definition (fix the code, never the snapshot). Generated ids
 * are renamed in order of appearance.
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { parityHtml } from '@/components/fx/__parity__/parity-utils';
import { SettingsProvider } from '@/providers/settings-provider';
import type { EmailLogDetail, EmailLogListItem } from '@/types/templates';
import EmailLogPage from '../page';
import { EmailDetailView } from '../components/email-detail-view';

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/settings/email-log'),
  useParams: vi.fn(() => ({})),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { name: 'Demo Admin', permissions: [], timezone: 'Asia/Kuala_Lumpur' } },
    status: 'authenticated',
    update: vi.fn(),
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

const row = (over: Partial<EmailLogListItem>): EmailLogListItem => ({
  id: 'em-1',
  toEmail: 'kay@acme.test',
  subject: 'Reset your password',
  templateKey: 'auth.reset_password',
  status: 'SENT',
  attempts: 1,
  usedFallback: false,
  createdAt: '2026-11-05T07:04:00Z',
  sentAt: '2026-11-05T07:04:05Z',
  nextAttemptAt: null,
  ...over,
});
const ROWS: EmailLogListItem[] = [
  row({}),
  row({ id: 'em-2', status: 'FAILED', attempts: 3, sentAt: null, subject: 'Your invoice', templateKey: 'billing.invoice' }),
  row({ id: 'em-3', status: 'PENDING', attempts: 0, sentAt: null, nextAttemptAt: '2026-11-05T08:00:00Z' }),
];
const DETAIL: EmailLogDetail = {
  ...ROWS[1],
  htmlBody: '<p>Hello <b>Kay</b></p>',
  textBody: 'Hello Kay',
  lastError: 'SMTP 550 mailbox unavailable',
  connectionId: 'conn-9',
};

vi.mock('@/services/email-log-service', () => ({
  EMAIL_LOG_SEGMENTS: [
    { id: 'all', label: 'All' },
    { id: 'pending', label: 'Pending' },
    { id: 'sent', label: 'Sent' },
    { id: 'failed', label: 'Failed' },
    { id: 'cancelled', label: 'Cancelled' },
  ],
  emailLogService: {
    list: vi.fn(async () => ({ data: ROWS, total: ROWS.length, page: 0 })),
    export: vi.fn(async () => ''),
    get: vi.fn(async (id: string) => (id === DETAIL.id ? DETAIL : null)),
    getAt: vi.fn(async () => ({ email: ROWS[1], total: 3 })),
    retry: vi.fn(),
    cancel: vi.fn(),
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
  window.localStorage.clear();
  window.sessionStorage.clear();
});

describe('parity (switch off): email log', () => {
  it('list with rows', async () => {
    const { container } = render(
      <SettingsProvider>
        <EmailLogPage />
      </SettingsProvider>,
    );
    await screen.findByText('Your invoice');
    expect(stable(container)).toMatchSnapshot();
  });

  it('one email: Overview, then the Body tab in its three views', async () => {
    const { container } = render(<EmailDetailView emailId="em-2" />, { wrapper: SettingsProvider });
    await screen.findByTestId('email-last-error');
    expect(stable(container)).toMatchSnapshot();

    fireEvent.mouseDown(screen.getByRole('tab', { name: /Body/ }));
    fireEvent.click(screen.getByRole('tab', { name: /Body/ }));
    await screen.findByTestId('email-body-frame');
    expect(stable(container)).toMatchSnapshot();

    fireEvent.click(screen.getByTestId('body-view-html'));
    expect(stable(container)).toMatchSnapshot();

    fireEvent.click(screen.getByTestId('body-view-text'));
    expect(stable(container)).toMatchSnapshot();
  });

  it('email not found', async () => {
    const { container } = render(<EmailDetailView emailId="nope" />, { wrapper: SettingsProvider });
    await screen.findByText('Email not found.');
    expect(stable(container)).toMatchSnapshot();
  });
});
