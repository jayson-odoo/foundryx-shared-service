import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FX_PRESETS_STORAGE_KEY } from '@/lib/fx/presets';
import { FX_SETTINGS_STORAGE_KEY } from '@/lib/fx/settings-schema';
import { FxProvider } from '@/providers/fx-provider';
import { TooltipProvider } from '@/components/ui/tooltip';
import { ThemePanel } from '@/components/fx/theme/theme-panel';
import { closeFxAdvanced, openFxAdvanced } from './advanced-open';
import { AdvancedSettings, formatFxValue } from './advanced-panel';

const toastMock = vi.hoisted(() => ({ success: vi.fn() }));
vi.mock('@/lib/toast', () => ({ toast: toastMock }));
vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
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
  window.localStorage.clear();
  resetHtml();
  toastMock.success.mockReset();
});

afterEach(() => {
  act(() => closeFxAdvanced());
});

function renderPanel({ on = true, open = true } = {}) {
  const utils = render(
    <FxProvider initial={on} initialTheme={FX_DEFAULT_THEME}>
      <TooltipProvider>
        <ThemePanel />
        <AdvancedSettings />
      </TooltipProvider>
    </FxProvider>,
  );
  if (open) act(() => openFxAdvanced());
  return utils;
}

const panel = () => screen.getByRole('dialog', { name: 'Advanced settings' });
const sw = (name: string) => within(panel()).getByRole('switch', { name });
const stored = () =>
  JSON.parse(window.localStorage.getItem(FX_SETTINGS_STORAGE_KEY) ?? '{}');
const storedPresets = () =>
  JSON.parse(window.localStorage.getItem(FX_PRESETS_STORAGE_KEY) ?? '[]');

function presetFile(body: unknown, name = 'preset.json') {
  const text = typeof body === 'string' ? body : JSON.stringify(body);
  const file = new File([text], name, { type: 'application/json' });
  Object.defineProperty(file, 'text', { value: () => Promise.resolve(text) });
  return file;
}

async function importFile(file: File) {
  const input = screen.getByTestId('fx-preset-file');
  await act(async () => {
    fireEvent.change(input, { target: { files: [file] } });
  });
}

describe('Advanced settings panel', () => {
  it('renders nothing until opened', () => {
    renderPanel({ open: false });
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('opens from the Theme panel link', () => {
    renderPanel({ open: false });
    fireEvent.click(screen.getByRole('button', { name: 'Advanced settings' }));
    expect(panel()).toBeInTheDocument();
  });

  it('shows only rows whose behaviour exists in merged slices', () => {
    renderPanel();
    const p = panel();
    expect(
      within(p).getByRole('region', { name: 'Motion' }),
    ).toBeInTheDocument();
    expect(
      within(p).getByRole('region', { name: 'Scrollbars' }),
    ).toBeInTheDocument();
    expect(sw('Animations')).toBeInTheDocument();
    expect(sw('Slim scrollbars')).toBeInTheDocument();
    expect(within(p).getByText('Thickness')).toBeInTheDocument();
    // Built by the actions (F2) and lists (F3a, F3b) slices.
    for (const built of [
      'Hover lift',
      'Press and hold to confirm',
      'Styled tooltips',
      'Smart view and Table view',
      'Shimmer on loading placeholders',
      'Reach around the text',
    ])
      expect(within(p).getByText(built), built).toBeInTheDocument();
    expect(sw('Hold to Copy')).toBeInTheDocument();
    for (const notBuilt of [
      'Cross-fade on theme changes',
      'Clipboard',
      'Show the submenu safe zone',
      'Tool Background strength',
    ])
      expect(within(p).queryByText(notBuilt), notBuilt).toBeNull();
    // Master switch plus the fifteen built switches.
    expect(within(p).getAllByRole('switch')).toHaveLength(16);
  });

  it('finds a setting by name or note and hides sections with nothing left', () => {
    renderPanel();
    const find = within(panel()).getByRole('searchbox', {
      name: 'Find a setting',
    });
    fireEvent.change(find, { target: { value: 'width' } });
    expect(within(panel()).getByText('Thickness')).toBeInTheDocument();
    expect(
      within(panel()).queryByRole('region', { name: 'Motion' }),
    ).toBeNull();
    fireEvent.change(find, { target: { value: 'jumping' } });
    expect(sw('Animations')).toBeInTheDocument();
    expect(
      within(panel()).queryByRole('region', { name: 'Scrollbars' }),
    ).toBeNull();
    fireEvent.change(find, { target: { value: 'zzz' } });
    expect(
      within(panel()).getByText('No setting matches.'),
    ).toBeInTheDocument();
  });

  it('applies a switch at once, hides the rows under it, and marks the change', () => {
    renderPanel();
    fireEvent.click(sw('Slim scrollbars'));
    expect(document.documentElement.getAttribute('data-fx-scroll')).toBe('off');
    expect(stored()).toEqual({ scroll: false });
    expect(within(panel()).queryByText('Thickness')).toBeNull();
    expect(within(panel()).getByText('Slim scrollbars').className).toContain(
      'text-(--fx-link)',
    );
  });

  it('steps a number setting and shows its unit', () => {
    renderPanel();
    const thumb = within(panel()).getByRole('slider', { name: 'Thickness' });
    expect(thumb).toHaveAttribute('aria-valuetext', '4 px');
    fireEvent.keyDown(thumb, { key: 'ArrowRight' });
    expect(stored()).toEqual({ 'scroll-size': 5 });
    expect(
      document.documentElement.style.getPropertyValue('--fx-scroll-size'),
    ).toBe('5px');
    expect(within(panel()).getByText('5 px')).toBeInTheDocument();
  });

  it('resets one section, then everything', () => {
    renderPanel();
    fireEvent.click(sw('Animations'));
    fireEvent.click(sw('Slim scrollbars'));
    expect(stored()).toEqual({ motion: false, scroll: false });
    fireEvent.click(
      within(panel()).getByRole('button', { name: 'Reset Motion' }),
    );
    expect(stored()).toEqual({ scroll: false });
    expect(sw('Animations')).toHaveAttribute('aria-checked', 'true');
    fireEvent.click(within(panel()).getByRole('button', { name: 'Reset all' }));
    expect(window.localStorage.getItem(FX_SETTINGS_STORAGE_KEY)).toBeNull();
    expect(sw('Slim scrollbars')).toHaveAttribute('aria-checked', 'true');
    expect(document.documentElement.hasAttribute('data-fx-scroll')).toBe(false);
  });

  it('saves a preset (a name is required), then deletes it with Undo', () => {
    renderPanel();
    fireEvent.click(sw('Animations'));
    fireEvent.click(
      within(panel()).getByRole('button', { name: 'Save preset' }),
    );
    const nameBox = within(panel()).getByLabelText('Preset name');
    fireEvent.submit(nameBox.closest('form')!);
    expect(within(panel()).getByRole('alert')).toHaveTextContent(
      'Give it a name.',
    );
    fireEvent.change(nameBox, { target: { value: 'Calm' } });
    fireEvent.submit(nameBox.closest('form')!);
    expect(storedPresets()).toEqual([
      { name: 'Calm', settings: { motion: false } },
    ]);
    expect(toastMock.success).toHaveBeenCalledWith('Saved preset "Calm"');
    expect(
      within(panel()).getByRole('combobox', { name: 'Preset' }),
    ).toHaveTextContent('Calm');

    fireEvent.click(
      within(panel()).getByRole('button', { name: 'Delete "Calm"' }),
    );
    expect(storedPresets()).toEqual([]);
    // The settings stay as they are.
    expect(stored()).toEqual({ motion: false });
    const [message, options] = toastMock.success.mock.calls.at(-1)!;
    expect(message).toBe('Deleted preset "Calm"');
    expect(options.action.label).toBe('Undo');
    act(() => options.action.onClick());
    expect(storedPresets()).toEqual([
      { name: 'Calm', settings: { motion: false } },
    ]);
  });

  it('shows "Custom (not saved)" when the settings match no preset', () => {
    renderPanel();
    const combo = within(panel()).getByRole('combobox', { name: 'Preset' });
    expect(combo).toHaveTextContent('Playbook defaults');
    fireEvent.click(sw('Animations'));
    expect(combo).toHaveTextContent('Custom (not saved)');
  });

  it('exports the current settings as a preset file holding only what differs', async () => {
    let blob: Blob | null = null;
    const create = vi.fn((b: Blob) => {
      blob = b;
      return 'blob:preset';
    });
    const revoke = vi.fn();
    Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke });
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => {});
    renderPanel();
    fireEvent.click(sw('Animations'));
    fireEvent.click(
      within(panel()).getByRole('button', { name: 'Export preset' }),
    );
    expect(click).toHaveBeenCalled();
    expect(JSON.parse(await blob!.text())).toEqual({
      type: 'foundryx-uiux-preset',
      version: 1,
      name: 'Custom',
      settings: { motion: false },
    });
    expect(toastMock.success).toHaveBeenCalledWith('Exported "Custom"');
    click.mockRestore();
  });

  it('imports a preset file, clamped to the schema, renaming a clash', async () => {
    window.localStorage.setItem(
      FX_PRESETS_STORAGE_KEY,
      JSON.stringify([{ name: 'Wide', settings: { scroll: false } }]),
    );
    renderPanel();
    await importFile(
      presetFile({
        type: 'foundryx-uiux-preset',
        version: 1,
        name: 'Wide',
        settings: { 'scroll-size': 40, motion: 'no', bogus: true },
      }),
    );
    expect(stored()).toEqual({ 'scroll-size': 12 });
    expect(storedPresets()).toEqual([
      { name: 'Wide', settings: { scroll: false } },
      { name: 'Wide (2)', settings: { 'scroll-size': 12 } },
    ]);
    expect(toastMock.success).toHaveBeenCalledWith('Imported "Wide (2)"');
    expect(
      within(panel()).getByRole('combobox', { name: 'Preset' }),
    ).toHaveTextContent('Wide (2)');
  });

  it('refuses junk with a plain message and changes nothing', async () => {
    renderPanel();
    await importFile(presetFile('{"type":"something-else","settings":{}}'));
    await waitFor(() =>
      expect(within(panel()).getByRole('alert')).toHaveTextContent(
        "That file isn't a preset.",
      ),
    );
    await importFile(presetFile('not json at all'));
    expect(within(panel()).getByRole('alert')).toHaveTextContent(
      "That file isn't a preset.",
    );
    expect(window.localStorage.getItem(FX_SETTINGS_STORAGE_KEY)).toBeNull();
    expect(window.localStorage.getItem(FX_PRESETS_STORAGE_KEY)).toBeNull();
    expect(toastMock.success).not.toHaveBeenCalled();
  });

  it('with the master switch off shows only the master switch', () => {
    renderPanel();
    fireEvent.click(sw('Foundryx UIUX (0.71.0)'));
    expect(within(panel()).getAllByRole('switch')).toHaveLength(1);
    expect(within(panel()).queryByRole('searchbox')).toBeNull();
    expect(within(panel()).queryByRole('combobox')).toBeNull();
    expect(
      within(panel()).queryByRole('button', { name: 'Reset all' }),
    ).toBeNull();
  });

  it('closes with its close button and with Esc', () => {
    renderPanel();
    fireEvent.click(within(panel()).getByRole('button', { name: 'Close' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    act(() => openFxAdvanced());
    fireEvent.keyDown(sw('Animations'), { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('moves with the grip arrow keys, stays inside the window and remembers its place', () => {
    renderPanel();
    const grip = within(panel()).getByRole('button', { name: 'Move panel' });
    // jsdom has no layout: the panel measures 0 wide, so the window is the bound.
    fireEvent.keyDown(grip, { key: 'ArrowLeft', shiftKey: true });
    const saved = JSON.parse(window.localStorage.getItem('fx_adv_pos')!);
    expect(saved.x).toBe(window.innerWidth - 16 - 50);
    expect(saved.y).toBe(16);
    fireEvent.keyDown(grip, { key: 'ArrowUp', shiftKey: true });
    expect(JSON.parse(window.localStorage.getItem('fx_adv_pos')!).y).toBe(0);
  });
});

describe('formatFxValue', () => {
  it('shows units the playbook way', () => {
    const base = {
      key: 'k',
      area: 'motion',
      label: '',
      note: '',
      slice: 'F1',
      kind: 'number',
      default: 1,
      min: 0,
      max: 10,
      step: 0.1,
    } as const;
    expect(formatFxValue({ ...base, unit: 's' }, 0.30000000000000004)).toBe(
      '0.3 s',
    );
    expect(formatFxValue({ ...base, unit: 'px' }, 8)).toBe('8 px');
    expect(formatFxValue({ ...base, unit: '%' }, 92)).toBe('92%');
    expect(formatFxValue({ ...base, unit: 'rows' }, 50)).toBe('50 rows');
  });
});
