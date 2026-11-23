import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME, readCookie } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { TooltipProvider } from '@/components/ui/tooltip';
import { ThemeButton, ThemeDialog, ThemeMenuItem } from './theme-button';
import { scaleLabel, ThemePanel } from './theme-panel';

const themeState = vi.hoisted(() => ({ theme: 'light', setTheme: vi.fn() }));
vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: themeState.theme, setTheme: themeState.setTheme }),
}));

function resetHtml() {
  const html = document.documentElement;
  for (const attr of Array.from(html.attributes)) {
    if (attr.name.startsWith('data-fx')) html.removeAttribute(attr.name);
  }
  html.removeAttribute('style');
  for (const name of ['fx_uiux', 'fx_theme'])
    document.cookie = `${name}=; Path=/; Max-Age=0`;
}

beforeEach(() => {
  themeState.theme = 'light';
  themeState.setTheme.mockReset();
  resetHtml();
});

function renderPanel(on: boolean) {
  return render(
    <FxProvider initial={on} initialTheme={FX_DEFAULT_THEME}>
      <ThemePanel />
    </FxProvider>,
  );
}

const pickCards = (names: string[]) =>
  names.map((name) => screen.queryByRole('button', { name }));

describe('Theme panel', () => {
  it('with the switch off shows only the master switch, named with the playbook version', () => {
    renderPanel(false);
    const toggle = screen.getByRole('switch', {
      name: 'Foundryx UIUX (0.71.0)',
    });
    expect(toggle).toHaveAttribute('aria-checked', 'false');
    expect(screen.queryByText('Mode')).toBeNull();
    expect(screen.queryByText('Palette')).toBeNull();
    expect(screen.queryByText('Font')).toBeNull();
    expect(screen.queryByRole('slider')).toBeNull();
    expect(screen.queryByText('Advanced settings')).toBeNull();
    expect(screen.getAllByRole('switch')).toHaveLength(1);
  });

  it('turning the master switch on reveals the theme controls', () => {
    renderPanel(false);
    fireEvent.click(
      screen.getByRole('switch', { name: 'Foundryx UIUX (0.71.0)' }),
    );
    expect(readCookie(document.cookie, 'fx_uiux')).toBe('on');
    expect(screen.getByText('Mode')).toBeInTheDocument();
    expect(screen.getByRole('slider')).toBeInTheDocument();
  });

  it('light mode shows only the light palettes', () => {
    renderPanel(true);
    expect(screen.getByText('Palette')).toBeInTheDocument();
    expect(pickCards(['Slate', 'Sand', 'Mint']).every(Boolean)).toBe(true);
    expect(pickCards(['Midnight', 'Graphite', 'Forest']).some(Boolean)).toBe(
      false,
    );
  });

  it('dark mode shows only the dark palettes', () => {
    themeState.theme = 'dark';
    renderPanel(true);
    expect(pickCards(['Midnight', 'Graphite', 'Forest']).every(Boolean)).toBe(
      true,
    );
    expect(pickCards(['Slate', 'Sand', 'Mint']).some(Boolean)).toBe(false);
  });

  it('Auto shows both, headed "Light palette" and "Dark palette"', () => {
    themeState.theme = 'system';
    renderPanel(true);
    expect(screen.getByText('Light palette')).toBeInTheDocument();
    expect(screen.getByText('Dark palette')).toBeInTheDocument();
    expect(screen.queryByText('Palette')).toBeNull();
    expect(pickCards(['Slate', 'Midnight']).every(Boolean)).toBe(true);
  });

  it('Mode uses the shared next-themes setting', () => {
    renderPanel(true);
    fireEvent.click(screen.getByRole('radio', { name: 'Dark' }));
    expect(themeState.setTheme).toHaveBeenCalledWith('dark');
    fireEvent.click(screen.getByRole('radio', { name: 'Auto' }));
    expect(themeState.setTheme).toHaveBeenCalledWith('system');
  });

  it('picking a palette and a font applies and remembers them', () => {
    renderPanel(true);
    fireEvent.click(screen.getByRole('button', { name: 'Mint' }));
    expect(document.documentElement.getAttribute('data-fx-pal')).toBe('mint');
    expect(screen.getByRole('button', { name: 'Mint' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    fireEvent.click(screen.getByRole('button', { name: 'Plus Jakarta Sans' }));
    expect(document.documentElement.getAttribute('data-fx-font')).toBe(
      'jakarta',
    );
    expect(readCookie(document.cookie, 'fx_theme')).toBe(
      'mint.midnight.jakarta.90',
    );
  });

  it('offers Geist (default), Jakarta, Inter, Manrope and DM Sans', () => {
    renderPanel(true);
    for (const name of [
      'Geist',
      'Plus Jakarta Sans',
      'Inter',
      'Manrope',
      'DM Sans',
    ]) {
      expect(screen.getByRole('button', { name })).toBeInTheDocument();
    }
    expect(screen.getByRole('button', { name: 'Geist' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });

  it('the size slider sits on Normal (90%) and snaps step by step', () => {
    renderPanel(true);
    const slider = screen.getByRole('slider');
    expect(slider).toHaveAttribute('aria-valuenow', '3');
    expect(slider).toHaveAttribute('aria-valuetext', '90%');
    expect(screen.getByText('Normal (90%)')).toBeInTheDocument();

    act(() => {
      fireEvent.keyDown(slider, { key: 'ArrowRight' });
    });
    expect(slider).toHaveAttribute('aria-valuenow', '4');
    expect(screen.getByText('100%')).toBeInTheDocument();
    expect(document.documentElement.style.getPropertyValue('--fx-scale')).toBe(
      '1',
    );

    act(() => {
      fireEvent.keyDown(slider, { key: 'Home' });
    });
    expect(screen.getByText('75%')).toBeInTheDocument();
    expect(readCookie(document.cookie, 'fx_theme')).toBe(
      'slate.midnight.geist.75',
    );
  });

  it('size labels follow the playbook wording', () => {
    expect(scaleLabel(90)).toBe('Normal (90%)');
    expect(scaleLabel(110)).toBe('110%');
  });
});

describe('Theme button', () => {
  it('shows with the switch off, marked as the switch entry, and opens the panel', async () => {
    render(
      <FxProvider initial={false} initialTheme={FX_DEFAULT_THEME}>
        <TooltipProvider>
          <ThemeButton />
        </TooltipProvider>
      </FxProvider>,
    );
    const button = screen.getByRole('button', { name: 'Theme' });
    expect(button).toHaveAttribute('data-fx-entry');
    fireEvent.click(button);
    const panel = await screen.findByRole('dialog', { name: 'Theme' });
    expect(
      within(panel).getByRole('switch', { name: 'Foundryx UIUX (0.71.0)' }),
    ).toBeInTheDocument();
  });

  it('renders nothing outside the switch provider', () => {
    const { container } = render(<ThemeButton />);
    expect(container.innerHTML).toBe('');
  });
});

describe('Theme entry on phones', () => {
  const desktopWidth = window.innerWidth;

  function renderMenu(onOpen = vi.fn()) {
    return render(
      <FxProvider initial={false} initialTheme={FX_DEFAULT_THEME}>
        <DropdownMenu open>
          <DropdownMenuTrigger>User menu</DropdownMenuTrigger>
          <DropdownMenuContent>
            <ThemeMenuItem onOpen={onOpen} />
          </DropdownMenuContent>
        </DropdownMenu>
      </FxProvider>,
    );
  }

  it('is a "Theme" row in the user menu at phone width', async () => {
    Object.defineProperty(window, 'innerWidth', {
      configurable: true,
      value: 375,
    });
    try {
      const onOpen = vi.fn();
      renderMenu(onOpen);
      const item = await screen.findByRole('menuitem', { name: 'Theme' });
      expect(item).toHaveAttribute('data-fx-entry');
      fireEvent.click(item);
      expect(onOpen).toHaveBeenCalled();
    } finally {
      Object.defineProperty(window, 'innerWidth', {
        configurable: true,
        value: desktopWidth,
      });
    }
  });

  it('is absent from the user menu on wider screens (the top bar has the button)', async () => {
    Object.defineProperty(window, 'innerWidth', {
      configurable: true,
      value: 1280,
    });
    try {
      renderMenu();
      await screen.findByRole('menu');
      expect(screen.queryByRole('menuitem', { name: 'Theme' })).toBeNull();
    } finally {
      Object.defineProperty(window, 'innerWidth', {
        configurable: true,
        value: desktopWidth,
      });
    }
  });

  it('opens the same panel in a dialog', async () => {
    render(
      <FxProvider initial={false} initialTheme={FX_DEFAULT_THEME}>
        <ThemeDialog open onOpenChange={vi.fn()} />
      </FxProvider>,
    );
    const dialog = await screen.findByRole('dialog', { name: 'Theme' });
    expect(
      within(dialog).getByRole('switch', { name: 'Foundryx UIUX (0.71.0)' }),
    ).toBeInTheDocument();
  });
});
