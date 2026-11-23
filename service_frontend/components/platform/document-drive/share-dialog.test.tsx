import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi, beforeEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { TooltipsProvider } from '@/providers/tooltips-provider';
import { ShareDialog } from './share-dialog';
import type { ShareRow, ShareUpdatePayload } from '@/types/documents';

const zone = vi.hoisted(() => ({ value: 'Asia/Kuala_Lumpur' }));

vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { name: 'Kay Tan', timezone: zone.value } }, status: 'authenticated' }),
}));

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

const KL = 'Asia/Kuala_Lumpur';
const LA = 'America/Los_Angeles';

function Look({ fx, children }: { fx: boolean; children: ReactNode }) {
  return (
    <FxProvider initial={fx} initialTheme={FX_DEFAULT_THEME}>
      <TooltipsProvider>{children}</TooltipsProvider>
    </FxProvider>
  );
}

async function settle() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 20));
  });
}

/** Opens the dialog on `stored`; the fake server keeps what is patched. */
async function open(fx: boolean, stored: Partial<ShareRow> = {}) {
  let row: ShareRow = { ...baseShare, ...stored };
  ensureShare.mockResolvedValue(row);
  updateShare.mockImplementation(async (_id: string, body: ShareUpdatePayload) => {
    row = {
      ...row,
      ...('expiresAt' in body ? { expiresAt: body.expiresAt ?? null } : {}),
      ...('password' in body ? { hasPassword: Boolean(body.password) } : {}),
    };
    return row;
  });
  const view = render(
    <Look fx={fx}>
      <ShareDialog target={TARGET} ceiling="edit" canManage onClose={() => {}} />
    </Look>,
  );
  await screen.findByTestId('share-url');
  await settle();
  return view;
}

const expirySwitch = () => screen.getByRole('switch', { name: 'Expiry date' });
const passwordSwitch = () => screen.getByRole('switch', { name: 'Password' });
const dayField = (fx: boolean) =>
  (fx
    ? screen.queryByRole('textbox', { name: 'Expiry date' })
    : screen.queryByLabelText('Expiry date', { selector: 'input' })) as HTMLInputElement | null;

/** Enters `day` (YYYY-MM-DD) the way each look's field takes it. */
async function pickDay(fx: boolean, day: string) {
  const input = dayField(fx) as HTMLInputElement;
  if (fx) {
    const [y, mo, d] = day.split('-');
    fireEvent.change(input, { target: { value: `${d}/${mo}/${y}` } });
    fireEvent.blur(input);
  } else {
    fireEvent.change(input, { target: { value: day } });
  }
  await settle();
}

/** The day the field shows, as YYYY-MM-DD. */
function shownDay(fx: boolean): string {
  const value = (dayField(fx) as HTMLInputElement).value;
  if (!fx) return value;
  const [d, mon, y] = value.split(' ');
  const mo = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'].indexOf(mon) + 1;
  return `${y}-${String(mo).padStart(2, '0')}-${d.padStart(2, '0')}`;
}

describe.each([
  ['old look', false],
  ['new look', true],
])('ShareDialog expiry and password (%s)', (_name, fx) => {
  beforeEach(() => {
    zone.value = KL;
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-11-18T04:00:00Z'));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('the Expiry switch opens the date field and closing it sends nothing', async () => {
    await open(fx);
    expect(dayField(fx)).toBeNull();
    expect(expirySwitch()).toHaveAttribute('aria-checked', 'false');
    fireEvent.click(expirySwitch());
    await settle();
    expect(expirySwitch()).toHaveAttribute('aria-checked', 'true');
    expect(dayField(fx)).not.toBeNull();
    fireEvent.click(expirySwitch());
    await settle();
    expect(expirySwitch()).toHaveAttribute('aria-checked', 'false');
    expect(dayField(fx)).toBeNull();
    expect(updateShare).not.toHaveBeenCalled();
  });

  it('the Password switch opens the password field and closing it sends nothing', async () => {
    await open(fx);
    expect(screen.queryByLabelText('Share password')).toBeNull();
    fireEvent.click(passwordSwitch());
    await settle();
    expect(passwordSwitch()).toHaveAttribute('aria-checked', 'true');
    fireEvent.change(screen.getByLabelText('Share password'), { target: { value: 'half typed' } });
    fireEvent.click(passwordSwitch());
    await settle();
    expect(passwordSwitch()).toHaveAttribute('aria-checked', 'false');
    expect(screen.queryByLabelText('Share password')).toBeNull();
    expect(updateShare).not.toHaveBeenCalled();
  });

  it('a password typed in the opened field is set, then removed by the switch', async () => {
    await open(fx);
    fireEvent.click(passwordSwitch());
    await settle();
    fireEvent.change(screen.getByLabelText('Share password'), { target: { value: 's3cret pass' } });
    fireEvent.click(screen.getByRole('button', { name: fx ? 'Set password' : 'Set' }));
    await settle();
    expect(updateShare.mock.calls).toEqual([['s-1', { password: 's3cret pass' }]]);
    expect(screen.queryByLabelText('Share password')).toBeNull();
    expect(passwordSwitch()).toHaveAttribute('aria-checked', 'true');
    fireEvent.click(passwordSwitch());
    await settle();
    expect(updateShare.mock.calls[1]).toEqual(['s-1', { password: null }]);
    expect(passwordSwitch()).toHaveAttribute('aria-checked', 'false');
  });

  it.each([
    [KL, '2026-12-31T16:00:00.000Z'],
    [LA, '2027-01-01T08:00:00.000Z'],
  ])('a new expiry on 31 Dec 2026 in %s is sent as the end of that day there', async (tz, instant) => {
    zone.value = tz;
    await open(fx);
    fireEvent.click(expirySwitch());
    await settle();
    await pickDay(fx, '2026-12-31');
    expect(updateShare.mock.calls).toEqual([['s-1', { expiresAt: instant }]]);
    expect(shownDay(fx)).toBe('2026-12-31');
  });

  it.each([
    [KL, '2026-11-30T16:00:00.000Z', '2026-12-31T16:00:00.000Z'],
    [LA, '2026-12-01T08:00:00.000Z', '2027-01-01T08:00:00.000Z'],
  ])('an expiry moved to 31 Dec 2026 in %s is sent as the end of that day there', async (tz, stored, instant) => {
    zone.value = tz;
    await open(fx, { expiresAt: stored });
    expect(shownDay(fx)).toBe('2026-11-30');
    await pickDay(fx, '2026-12-31');
    expect(updateShare.mock.calls).toEqual([['s-1', { expiresAt: instant }]]);
  });

  it.each([
    [KL, '2026-12-31T16:00:00.000Z'],
    [LA, '2027-01-01T08:00:00.000Z'],
  ])('a share opened again in %s shows the day it was set to', async (tz, stored) => {
    zone.value = tz;
    await open(fx, { expiresAt: stored });
    expect(expirySwitch()).toHaveAttribute('aria-checked', 'true');
    expect(shownDay(fx)).toBe('2026-12-31');
    expect(updateShare).not.toHaveBeenCalled();
  });

  it('turning Expiry off clears a stored expiry', async () => {
    await open(fx, { expiresAt: '2026-12-31T16:00:00.000Z' });
    fireEvent.click(expirySwitch());
    await settle();
    expect(updateShare.mock.calls).toEqual([['s-1', { expiresAt: null }]]);
    expect(dayField(fx)).toBeNull();
  });

  it('the earliest day is today in the zone, not the UTC day', async () => {
    // 04:00 on 19 Nov in Kuala Lumpur, still 18 Nov in UTC.
    vi.setSystemTime(new Date('2026-11-18T20:00:00Z'));
    const view = await open(fx);
    fireEvent.click(expirySwitch());
    await settle();
    if (!fx) expect(dayField(fx)).toHaveAttribute('min', '2026-11-19');
    await pickDay(fx, '2026-11-18');
    expect(updateShare).not.toHaveBeenCalled();
    await pickDay(fx, '2026-11-19');
    expect(updateShare.mock.calls).toEqual([['s-1', { expiresAt: '2026-11-19T16:00:00.000Z' }]]);
    view.unmount();

    // 19:00 on 18 Nov in Los Angeles, already 19 Nov in UTC.
    updateShare.mockClear();
    zone.value = LA;
    vi.setSystemTime(new Date('2026-11-19T03:00:00Z'));
    await open(fx);
    fireEvent.click(expirySwitch());
    await settle();
    if (!fx) expect(dayField(fx)).toHaveAttribute('min', '2026-11-18');
    await pickDay(fx, '2026-11-18');
    expect(updateShare.mock.calls).toEqual([['s-1', { expiresAt: '2026-11-19T08:00:00.000Z' }]]);
  });
});
