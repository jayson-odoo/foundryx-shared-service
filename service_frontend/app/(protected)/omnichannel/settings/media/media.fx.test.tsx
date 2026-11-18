/**
 * Media limits with the Foundryx UIUX switch on (slice W2-WS): "Save media
 * settings" is the page's red action, greyed with "Nothing changed yet."
 * until a cap changes; the save sends exactly what it sends with the switch
 * off; a wrong size is named under its field; Undo writes the old caps back.
 * Switch off is pinned by `__parity__/media.parity.test.tsx`. Requests are
 * captured at `apiFetch`, under the real service.
 */
import type { ReactNode } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import { PageHeader } from '@/components/platform/page-header';
import { fxMediaPayload } from './fx-media-caps-form';
import { MediaCapsForm, seedValues } from './media-caps-form';
import { MEDIA_SETTINGS_FIXTURE } from './media-fixture.test-data';

const net = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock('@/lib/api-client', async (orig) => {
  const real = (await orig()) as Record<string, unknown>;
  return { ...real, apiFetch: net.apiFetch };
});
const toasts = vi.hoisted(() => ({
  fxDone: vi.fn(),
  error: vi.fn(),
  success: vi.fn(),
}));
vi.mock('@/lib/toast', async (orig) => {
  const real = (await orig()) as { toast: Record<string, unknown> };
  return { toast: { ...real.toast, ...toasts } };
});
vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}));
vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({
    push: vi.fn(),
    prefetch: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
  })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/omnichannel/settings/media'),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { name: 'Nurul Huda', permissions: [] } },
    status: 'authenticated',
  }),
}));
vi.mock('@/lib/impersonation-store', () => ({
  useImpersonationSession: () => null,
}));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));

function look(on: boolean) {
  return function Look({ children }: { children: ReactNode }) {
    return (
      <FxProvider initial={on} initialTheme={FX_DEFAULT_THEME}>
        <PageHeader title="Media" />
        {children}
      </FxProvider>
    );
  };
}

function writes() {
  return net.apiFetch.mock.calls
    .filter(([, init]) => (init as RequestInit | undefined)?.method)
    .map(([path, init]) => ({
      path,
      method: (init as RequestInit).method,
      body: (init as RequestInit).body ?? null,
    }));
}

beforeEach(() => {
  net.apiFetch.mockReset();
  Object.values(toasts).forEach((fn) => fn.mockReset());
  net.apiFetch.mockImplementation(async () => MEDIA_SETTINGS_FIXTURE);
});
afterEach(() => resetPageActionsForTests());

async function saveIn(on: boolean, values: Record<string, string>) {
  const view = render(<MediaCapsForm />, { wrapper: look(on) });
  await screen.findAllByLabelText('Maximum size (MB)');
  for (const [key, value] of Object.entries(values)) {
    fireEvent.change(document.getElementById(`cap-${key}`)!, {
      target: { value },
    });
  }
  fireEvent.click(screen.getByRole('button', { name: 'Save media settings' }));
  return view;
}

describe('the same save in both looks', () => {
  it('sends the same caps, blanks as null and sizes capped at the ceiling', async () => {
    const input = {
      imageMaxBytes: '3',
      videoMaxBytes: '99',
      documentMaxBytes: '',
    };
    (await saveIn(false, input)).unmount();
    await waitFor(() => expect(writes()).toHaveLength(1));
    const off = writes();
    net.apiFetch.mockClear();
    await saveIn(true, input);
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()).toEqual(off);
    expect(JSON.parse(String(off[0].body))).toEqual({
      imageMaxBytes: 3 * 1024 * 1024,
      videoMaxBytes: 16 * 1024 * 1024,
      audioMaxBytes: null,
      documentMaxBytes: null,
      stickerMaxBytes: null,
    });
  });

  it('the payload builder matches the switch-off rules for any input', () => {
    const values = {
      ...seedValues(MEDIA_SETTINGS_FIXTURE),
      imageMaxBytes: '-1',
      stickerMaxBytes: 'abc',
    };
    expect(fxMediaPayload(MEDIA_SETTINGS_FIXTURE, values)).toEqual({
      invalid: ['imageMaxBytes', 'stickerMaxBytes'],
    });
  });
});

describe('under the new look', () => {
  it('the red action is greyed with "Nothing changed yet." until a cap changes', async () => {
    render(<MediaCapsForm />, { wrapper: look(true) });
    expect(await screen.findByText('Nothing changed yet.')).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('button', { name: 'Save media settings' }),
    );
    expect(writes()).toHaveLength(0);
    fireEvent.change(document.getElementById('cap-imageMaxBytes')!, {
      target: { value: '4' },
    });
    expect(screen.queryByText('Nothing changed yet.')).not.toBeInTheDocument();
  });

  it('a wrong size is named under its field, with no toast and no request', async () => {
    await saveIn(true, { imageMaxBytes: '-2' });
    expect(
      await screen.findByText('Enter a size in MB, or leave it blank.'),
    ).toBeInTheDocument();
    expect(document.getElementById('cap-imageMaxBytes')).toHaveAttribute(
      'aria-invalid',
      'true',
    );
    expect(toasts.error).not.toHaveBeenCalled();
    expect(writes()).toHaveLength(0);
  });

  it('the done toast has an Undo that writes the old caps back', async () => {
    await saveIn(true, { imageMaxBytes: '4' });
    await waitFor(() => expect(toasts.fxDone).toHaveBeenCalled());
    const call = toasts.fxDone.mock.calls[0][0] as {
      what: string;
      byWhom: string;
      undo: () => void;
    };
    expect(call.what).toBe('Media limits saved');
    expect(call.byWhom).toBe('Nurul Huda');
    net.apiFetch.mockClear();
    call.undo();
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(JSON.parse(String(writes()[0].body))).toEqual(
      MEDIA_SETTINGS_FIXTURE.overrides,
    );
  });
});
