/**
 * Menu rows with the Foundryx UIUX switch ON: an enabled option must be
 * clickable and fully opaque, a genuinely disabled one blocked and faded.
 *
 * Regression: cmdk writes `data-disabled="false"` on EVERY enabled option and
 * a bare `data-disabled:` Tailwind variant matches any value of the
 * attribute, so options looked half-faded and ignored the mouse.
 *
 * jsdom has no Tailwind, so the real class strings are compiled with
 * Tailwind's own compiler and the output is injected as a stylesheet; jsdom
 * then resolves the cascade for `pointer-events` and `opacity`. This proves
 * the selectors; it does not prove real browser hit-testing (see the
 * browser check in the pull request).
 */
import type { ReactNode } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { compile } from 'tailwindcss';
import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { Command, CommandItem, CommandList } from '@/components/ui/command';
import { MultiSelect } from '@/components/platform/multi-select';
import { SearchSelect } from '@/components/platform/search-select';
import { FX_MENU_ROW } from './classes';

vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { timezone: 'Asia/Kuala_Lumpur' } },
    status: 'authenticated',
  }),
}));

function On({ children }: { children: ReactNode }) {
  return (
    <FxProvider initial initialTheme={FX_DEFAULT_THEME}>
      {children}
    </FxProvider>
  );
}

const options = [
  { label: 'Oak table', value: 'oak' },
  { label: 'Pine chair', value: 'pine' },
];

let styleEl: HTMLStyleElement;

beforeAll(async () => {
  const compiler = await compile('@tailwind utilities;');
  const css = compiler.build(FX_MENU_ROW.split(/\s+/).filter(Boolean));
  styleEl = document.createElement('style');
  // Tailwind 4 emits native CSS nesting (`.x { &[attr] { ... } }`), which
  // jsdom cannot cascade: flatten the one level it uses.
  styleEl.textContent = css.replace(
    /(\.[^\s{]+)\s*\{\s*&([^{]+)\{([^}]*)\}\s*\}/g,
    '$1$2{$3}',
  );
  document.head.appendChild(styleEl);
});

beforeEach(() => {
  document.cookie = 'fx_uiux=; Path=/; Max-Age=0';
});
afterEach(() => {
  for (const attr of Array.from(document.documentElement.attributes)) {
    if (attr.name.startsWith('data-fx'))
      document.documentElement.removeAttribute(attr.name);
  }
});

describe('FX_MENU_ROW disabled styling', () => {
  it('has no bare data-disabled variant, only value-keyed ones', () => {
    const classes = FX_MENU_ROW.split(/\s+/);
    expect(classes.filter((c) => /(^|:)data-disabled:/.test(c))).toEqual([]);
    expect(classes).toContain('data-[disabled=true]:pointer-events-none');
    expect(classes).toContain('data-[disabled=true]:opacity-50');
  });

  it('the compiled CSS keys blocking and fading on the attribute value', () => {
    const css = styleEl.textContent ?? '';
    expect(css).toContain('[data-disabled="true"]');
    expect(css).not.toMatch(/\[data-disabled\]/);
  });

  it('an enabled cmdk option (data-disabled="false") is neither blocked nor faded; a disabled one is both', () => {
    render(
      <Command>
        <CommandList>
          <CommandItem className={FX_MENU_ROW}>Enabled</CommandItem>
          <CommandItem className={FX_MENU_ROW} disabled>
            Disabled
          </CommandItem>
        </CommandList>
      </Command>,
    );
    const enabled = screen.getByText('Enabled');
    const disabled = screen.getByText('Disabled');
    expect(enabled).toHaveAttribute('data-disabled', 'false');
    expect(disabled).toHaveAttribute('data-disabled', 'true');
    expect(getComputedStyle(enabled).pointerEvents).not.toBe('none');
    expect(getComputedStyle(enabled).opacity).not.toMatch(/^(0\.5|50%)$/);
    expect(getComputedStyle(disabled).pointerEvents).toBe('none');
    expect(getComputedStyle(disabled).opacity).toMatch(/^(0\.5|50%)$/);
  });

  it('a Radix-style disabled row (data-disabled="") is still blocked and faded', () => {
    render(
      <div className={FX_MENU_ROW} data-disabled="" data-testid="radix-row">
        Row
      </div>,
    );
    expect(
      getComputedStyle(screen.getByTestId('radix-row')).pointerEvents,
    ).toBe('none');
  });
});

describe('real pointer click on options (switch on)', () => {
  it('selects an option of the searchable dropdown', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <SearchSelect
        ariaLabel="Product"
        options={options}
        value={null}
        onChange={onChange}
      />,
      { wrapper: On },
    );
    await user.click(screen.getByRole('combobox', { name: 'Product' }));
    const option = screen.getByRole('option', { name: /Pine chair/ });
    expect(option.className).toContain(
      'data-[disabled=true]:pointer-events-none',
    );
    expect(option.className).not.toMatch(/(^|\s)data-disabled:/);
    expect(getComputedStyle(option).pointerEvents).not.toBe('none');
    await user.click(option);
    expect(onChange).toHaveBeenCalledWith('pine');
  });

  it('toggles an option of the multi-select', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<MultiSelect options={options} value={[]} onChange={onChange} />, {
      wrapper: On,
    });
    await user.click(screen.getByRole('combobox'));
    const option = screen.getByRole('option', { name: /Oak table/ });
    expect(option.className).not.toMatch(/(^|\s)data-disabled:/);
    expect(getComputedStyle(option).pointerEvents).not.toBe('none');
    await user.click(option);
    expect(onChange).toHaveBeenCalledWith(['oak']);
  });
});
