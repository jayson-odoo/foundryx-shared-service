/**
 * Foundation follow-up from the first page wave, actions side: the icon set
 * and drawn icons (FX-21), the page header's More list (FX-16).
 */
import type { ReactNode } from 'react';
import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { FX_ICONS, FxIcon } from '@/components/fx/icons';
import { FxOtherActions } from './other-actions';
import { PageHeader } from '@/components/platform/page-header';
import {
  resetPageActionsForTests,
  useRegisterOtherActions,
  type FxOtherActionSpec,
} from './page-actions-context';

vi.mock('next/navigation', () => ({
  usePathname: () => '/omnichannel/contacts',
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));

function On({ children }: { children: ReactNode }) {
  return (
    <FxProvider initial initialTheme={FX_DEFAULT_THEME}>
      {children}
    </FxProvider>
  );
}

afterEach(() => {
  resetPageActionsForTests();
});

describe('FX-21 icons', () => {
  it('holds the meanings the first wave drew for itself', () => {
    for (const name of [
      'snooze',
      'panel',
      'save-draft',
      'test-message',
      'attach',
      'emoji',
      'quick-reply',
      'voice',
      'up',
      'down',
    ]) {
      expect(FX_ICONS).toHaveProperty(name);
    }
    const { container } = render(<FxIcon name="snooze" />);
    expect(container.querySelector('svg')).not.toBeNull();
    // CSV import and export are the file icons, not new glyphs.
    const files = render(<FxIcon name="csv-up" />);
    expect(files.container.querySelector('[data-fx-file="CSV"]')).not.toBeNull();
  });

  it('an Other Action takes a drawn icon node as well as a name', () => {
    render(
      <On>
        <FxOtherActions
          actions={[
            {
              id: 'snooze',
              label: 'Snooze',
              icon: 'snooze',
              onClick: vi.fn(),
            },
            {
              id: 'shrug',
              label: 'Shrug',
              icon: <svg data-testid="own-icon" aria-hidden="true" />,
              onClick: vi.fn(),
            },
          ]}
          moreIds={[]}
        />
      </On>,
    );
    const own = screen.getByRole('button', { name: 'Shrug' });
    expect(own.querySelector('[data-testid="own-icon"]')).not.toBeNull();
    expect(screen.getByRole('button', { name: 'Snooze' }).querySelector('svg')).not.toBeNull();
  });
});

function RegistersOthers({ actions, moreIds }: { actions: FxOtherActionSpec[]; moreIds?: string[] }) {
  useRegisterOtherActions(actions, moreIds);
  return null;
}

describe('FX-16 the page header honours the More list', () => {
  const others: FxOtherActionSpec[] = [
    { id: 'export', label: 'Export', icon: 'csv-down', onClick: vi.fn() },
    { id: 'manage', label: 'Manage segments', icon: 'settings', onClick: vi.fn() },
  ];

  it('keeps the configured ids in More, the rest as icons', () => {
    render(
      <On>
        <PageHeader title="Contacts" />
        <RegistersOthers actions={others} />
        <RegistersOthers actions={[]} moreIds={['manage']} />
      </On>,
    );
    expect(screen.getByRole('button', { name: 'Export' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Manage segments' })).toBeNull();
    expect(screen.getByRole('button', { name: 'More' })).toBeInTheDocument();
  });

  it('without a More list every action stays an icon', () => {
    render(
      <On>
        <PageHeader title="Contacts" />
        <RegistersOthers actions={others} />
      </On>,
    );
    expect(screen.getByRole('button', { name: 'Manage segments' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'More' })).toBeNull();
  });
});
