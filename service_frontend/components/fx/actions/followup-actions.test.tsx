/**
 * Foundation follow-up from the first page wave, actions side: the icon set
 * and drawn icons (FX-21).
 */
import type { ReactNode } from 'react';
import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { FX_ICONS, FxIcon } from '@/components/fx/icons';
import { FxOtherActions } from './other-actions';
import { resetPageActionsForTests } from './page-actions-context';

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
