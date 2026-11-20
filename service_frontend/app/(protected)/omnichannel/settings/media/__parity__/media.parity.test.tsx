/**
 * Switch-off parity for the Media limits page (Foundryx UIUX slice W2-WS):
 * the page untouched and with one cap changed, rendered with the switch OFF.
 * Recorded on the code as it was before the slice; a change that needs one of
 * these snapshots updated is wrong by definition (fix the code, never the
 * snapshot).
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { parityHtml } from '@/components/fx/__parity__/parity-utils';
import { SettingsProvider } from '@/providers/settings-provider';
import { MEDIA_SETTINGS_FIXTURE } from '../media-fixture.test-data';
import MediaLimitsPage from '../page';

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/omnichannel/settings/media'),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { name: 'Demo Admin', permissions: [] } }, status: 'authenticated' }),
}));
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>() }),
}));
vi.mock('@/components/common/require-permission', () => ({
  RequirePermission: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));
vi.mock('@/services/omnichannel-settings-service', () => ({
  omnichannelSettingsService: {
    get: vi.fn(async () => MEDIA_SETTINGS_FIXTURE),
    update: vi.fn(),
  },
}));

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

describe('parity (switch off): Media limits', () => {
  it('untouched, then with one cap changed', async () => {
    const { container } = render(
      <SettingsProvider>
        <MediaLimitsPage />
      </SettingsProvider>,
    );
    const image = await screen.findByLabelText('Maximum size (MB)', { selector: '#cap-imageMaxBytes' });
    expect(stable(container)).toMatchSnapshot();
    fireEvent.change(image, { target: { value: '3' } });
    expect(stable(container)).toMatchSnapshot();
  });
});
