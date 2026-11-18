/**
 * Foundryx UIUX fields (slice F4) with the switch ON: the shared primitives
 * branch to the fx fields with the same props, and the new fields follow the
 * playbook rules. The switch-off markup is pinned by
 * `components/fx/__parity__/fields.parity.test.tsx`.
 */
import { act, fireEvent, render, renderHook, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Slider, SliderThumb } from '@/components/ui/slider';
import { Switch } from '@/components/ui/switch';
import { SearchSelect } from '@/components/platform/search-select';
import { MultiSelect } from '@/components/platform/multi-select';
import { DateRangePicker } from '@/components/platform/date-range-picker';
import { SecretInput } from '@/components/platform/secret-input';
import { useDatetime } from '@/hooks/use-datetime';
import {
  FxDateField,
  FxMoneyField,
  FxPasswordStrength,
  FxSecretOnce,
  FxStepper,
  FxValueCardStepper,
  fxRangeLabel,
  nextSegmentValue,
  resolveFxPresetRange,
} from '@/components/fx/fields';

vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { timezone: 'Asia/Kuala_Lumpur' } }, status: 'authenticated' }),
}));

function On({ children }: { children: ReactNode }) {
  return (
    <FxProvider initial initialTheme={FX_DEFAULT_THEME}>
      {children}
    </FxProvider>
  );
}

const renderOn = (ui: ReactNode) => render(ui, { wrapper: On });

function resetHtml() {
  const html = document.documentElement;
  for (const attr of Array.from(html.attributes)) {
    if (attr.name.startsWith('data-fx')) html.removeAttribute(attr.name);
  }
  html.removeAttribute('style');
  document.cookie = 'fx_uiux=; Path=/; Max-Age=0';
}

beforeEach(resetHtml);
afterEach(() => vi.useRealTimers());

describe('text fields', () => {
  it('branch to the fx field while on, keeping the touch text size', () => {
    renderOn(
      <>
        <Input aria-label="Name" variant="sm" />
        <Textarea aria-label="Note" />
      </>,
    );
    const input = screen.getByRole('textbox', { name: 'Name' });
    expect(input).toHaveAttribute('data-fx-field');
    expect(input.className).toContain('pointer-coarse:text-base');
    expect(input.className).toContain('enabled:hover:-translate-y-0.5');
    expect(screen.getByRole('textbox', { name: 'Note' })).toHaveAttribute('data-fx-field');
  });

  it('stay the old field with the switch off', () => {
    render(<Input aria-label="Name" />);
    expect(screen.getByRole('textbox', { name: 'Name' })).not.toHaveAttribute('data-fx-field');
  });
});

describe('moments while on', () => {
  it('use the 12-hour clock and the playbook date', () => {
    const { result } = renderHook(() => useDatetime(), { wrapper: On });
    expect(result.current.formatDateTime('2026-11-14T06:14:00Z')).toBe('14 Nov 2026, 2:14 pm');
    expect(result.current.formatTime('2026-11-14T06:14:00Z')).toBe('2:14 pm');
    expect(result.current.formatDate('2026-11-02T06:14:00Z')).toBe('2 Nov 2026');
    expect(result.current.zoneLine).toMatch(/^Kuala Lumpur time \(GMT\+8\)$/);
  });

  it('keep the 24-hour form with the switch off', () => {
    const { result } = renderHook(() => useDatetime());
    expect(result.current.formatDateTime('2026-11-14T06:14:00Z')).toBe('14 Nov 2026, 14:14');
  });
});

describe('searchable dropdown', () => {
  const options = [
    { label: 'Oak table', value: 'oak', description: 'SKU T-18' },
    { label: 'Pine chair', value: 'pine' },
    { label: 'Oak shelf', value: 'oak-shelf' },
  ];

  it('filters on any word, bolds the match and shows the second line', async () => {
    const user = userEvent.setup();
    renderOn(<SearchSelect ariaLabel="Product" options={options} value="pine" onChange={() => {}} />);
    await user.click(screen.getByRole('combobox', { name: 'Product' }));
    await user.keyboard('t-18');
    const list = screen.getByRole('listbox');
    expect(within(list).getAllByRole('option')).toHaveLength(1);
    expect(within(list).getByText('SKU', { exact: false })).toBeInTheDocument();
    expect(list.querySelector('b')?.textContent).toBe('T-18');
  });

  it('says what matched nothing, and offers Create only without an exact match', async () => {
    const user = userEvent.setup();
    renderOn(
      <SearchSelect ariaLabel="Product" options={options} value={null} onChange={() => {}} allowCustom noun="products" />,
    );
    await user.click(screen.getByRole('combobox', { name: 'Product' }));
    await user.keyboard('oak 18');
    // The one match, then the Create row.
    expect(within(screen.getByRole('listbox')).getAllByRole('option').map((o) => o.textContent)).toEqual([
      'Oak tableSKU T-18',
      'Create "oak 18"',
    ]);
    await user.clear(screen.getByRole('combobox', { name: '' }));
    await user.keyboard('walnut');
    expect(screen.getByText('No products match "walnut"')).toBeInTheDocument();
    expect(screen.getByText('Create "walnut"')).toBeInTheDocument();
    await user.clear(screen.getByRole('combobox', { name: '' }));
    await user.keyboard('Oak table');
    expect(screen.queryByText(/^Create/)).toBeNull();
  });

  it('shows at most 50 results, then asks to keep typing', async () => {
    const user = userEvent.setup();
    const many = Array.from({ length: 60 }, (_, i) => ({ label: `Item ${i}`, value: `i${i}` }));
    renderOn(<SearchSelect ariaLabel="Item" options={many} value={null} onChange={() => {}} total={1240} />);
    await user.click(screen.getByRole('combobox', { name: 'Item' }));
    expect(within(screen.getByRole('listbox')).getAllByRole('option')).toHaveLength(50);
    expect(screen.getByText('Keep typing to narrow 1,240 results')).toBeInTheDocument();
  });

  it('asks the server after a 0.25 s pause in typing', () => {
    vi.useFakeTimers();
    const onQueryChange = vi.fn();
    renderOn(<SearchSelect ariaLabel="Item" options={[]} value={null} onChange={() => {}} onQueryChange={onQueryChange} />);
    fireEvent.click(screen.getByRole('combobox', { name: 'Item' }));
    const box = screen.getAllByRole('combobox').find((el) => el.tagName === 'INPUT') as HTMLInputElement;
    fireEvent.change(box, { target: { value: 'o' } });
    fireEvent.change(box, { target: { value: 'oa' } });
    act(() => vi.advanceTimersByTime(200));
    expect(onQueryChange).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(60));
    expect(onQueryChange).toHaveBeenCalledTimes(1);
    expect(onQueryChange).toHaveBeenCalledWith('oa');
  });

  it('many choices: chips inside the field, the list stays open', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderOn(<MultiSelect options={options} value={['pine']} onChange={onChange} />);
    const trigger = screen.getByRole('combobox');
    expect(trigger.querySelector('[data-fx-chip]')?.textContent).toContain('Pine chair');
    await user.click(trigger);
    await user.click(screen.getByRole('option', { name: /Oak table/ }));
    expect(onChange).toHaveBeenCalledWith(['pine', 'oak']);
    expect(screen.getByRole('listbox')).toBeInTheDocument();
  });
});

describe('date field', () => {
  it('tidies a typed date when you leave the field', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderOn(<FxDateField aria-label="Due" value={null} onChange={onChange} today="2026-11-14" />);
    const field = screen.getByRole('textbox', { name: 'Due' });
    await user.type(field, 'tomorrow');
    await user.tab();
    expect(onChange).toHaveBeenCalledWith('2026-11-15');
    expect(field).toHaveValue('15 Nov 2026');
  });

  it('says how to write a date it cannot read, without moving layout', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderOn(<FxDateField aria-label="Due" value={null} onChange={onChange} today="2026-11-14" />);
    await user.type(screen.getByRole('textbox', { name: 'Due' }), 'soon');
    await user.tab();
    const message = screen.getByText('Enter a date, like 14 Nov 2026');
    expect(message.className).toContain('absolute');
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole('textbox', { name: 'Due' })).toHaveAttribute('aria-invalid', 'true');
  });

  it('refuses a day outside the allowed range', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderOn(
      <FxDateField aria-label="Due" value={null} onChange={onChange} today="2026-11-14" minDate="2026-11-14" />,
    );
    await user.type(screen.getByRole('textbox', { name: 'Due' }), 'yesterday');
    await user.tab();
    expect(screen.getByText('Pick a day from 14 Nov 2026')).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe('date range', () => {
  it('shows one field with the range', () => {
    renderOn(
      <DateRangePicker
        value={{ preset: 'custom', from: '2026-11-01', to: '2026-11-30' }}
        onChange={() => {}}
        timeZone="Asia/Kuala_Lumpur"
      />,
    );
    expect(screen.getByRole('button', { name: 'Date range: 1 Nov - 30 Nov 2026' })).toBeInTheDocument();
  });

  it('labels ranges, open ends and single days', () => {
    expect(fxRangeLabel('2025-12-28', '2026-01-03')).toBe('28 Dec 2025 - 3 Jan 2026');
    expect(fxRangeLabel('2026-11-14', '2026-11-14')).toBe('14 Nov 2026');
    expect(fxRangeLabel('2026-11-14', '')).toBe('From 14 Nov 2026');
    expect(fxRangeLabel('', '2026-11-14')).toBe('Until 14 Nov 2026');
  });

  it('resolves quick picks in the report zone, weeks from Monday', () => {
    // Saturday 14 Nov 2026, 11:30 pm UTC = Sunday 15 Nov in Kuala Lumpur.
    const now = new Date('2026-11-14T23:30:00Z');
    expect(resolveFxPresetRange('today', 'Asia/Kuala_Lumpur', now)).toEqual({ from: '2026-11-15', to: '2026-11-15' });
    expect(resolveFxPresetRange('today', 'UTC', now)).toEqual({ from: '2026-11-14', to: '2026-11-14' });
    expect(resolveFxPresetRange('thisWeek', 'Asia/Kuala_Lumpur', now)).toEqual({ from: '2026-11-09', to: '2026-11-15' });
    expect(resolveFxPresetRange('thisYear', 'UTC', now)).toEqual({ from: '2026-01-01', to: '2026-11-14' });
  });

  it('picks a quick pick from the open field', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderOn(
      <DateRangePicker
        value={{ preset: 'custom', from: '2026-11-01', to: '2026-11-30' }}
        onChange={onChange}
        timeZone="Asia/Kuala_Lumpur"
      />,
    );
    await user.click(screen.getByRole('button', { name: /Date range/ }));
    await user.click(screen.getByRole('button', { name: 'This month' }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ preset: 'thisMonth' }));
  });
});

describe('money field', () => {
  it('shows RM inside for MYR and tidies the amount on leaving', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderOn(<FxMoneyField aria-label="Price" value={null} onChange={onChange} currency="MYR" />);
    const field = screen.getByRole('textbox', { name: 'Price (RM)' });
    expect(field).toHaveAttribute('inputmode', 'decimal');
    expect(field.className).toContain('text-end');
    await user.type(field, '14000');
    await user.tab();
    expect(onChange).toHaveBeenCalledWith(14000);
    expect(field).toHaveValue('14,000.00');
  });

  it('shows the ISO code for any other currency, with its own decimals', () => {
    renderOn(<FxMoneyField aria-label="Price" value={1234} onChange={() => {}} currency="JPY" />);
    const field = screen.getByRole('textbox', { name: 'Price (JPY)' });
    expect(field).toHaveValue('1,234');
  });

  it('puts a short message under a wrong amount', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderOn(<FxMoneyField aria-label="Price" value={null} onChange={onChange} currency="SGD" />);
    await user.type(screen.getByRole('textbox', { name: 'Price (SGD)' }), '12abc');
    await user.tab();
    expect(screen.getByText('Enter an amount, like 14,000.00')).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe('steppers', () => {
  it('step with the buttons and the arrow keys, greyed at the ends', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { rerender } = renderOn(<FxStepper aria-label="Tax" value={9} onChange={onChange} min={0} max={10} />);
    await user.click(screen.getByRole('button', { name: 'Increase' }));
    expect(onChange).toHaveBeenLastCalledWith(10);
    rerender(<FxStepper aria-label="Tax" value={10} onChange={onChange} min={0} max={10} />);
    expect(screen.getByRole('button', { name: 'Increase' })).toBeDisabled();
    screen.getByRole('spinbutton', { name: 'Tax' }).focus();
    await user.keyboard('{ArrowDown}');
    expect(onChange).toHaveBeenLastCalledWith(9);
    expect(screen.getByRole('button', { name: 'Decrease' })).toBeEnabled();
  });

  it('keeps counting while held', () => {
    vi.useFakeTimers();
    let value = 1;
    const onChange = vi.fn((next: number) => {
      value = next;
    });
    renderOn(<FxStepper aria-label="Qty" value={value} onChange={onChange} min={1} max={99} />);
    const plus = screen.getByRole('button', { name: 'Increase' });
    fireEvent.pointerDown(plus);
    expect(onChange).toHaveBeenCalledTimes(1);
    act(() => vi.advanceTimersByTime(400 + 80 * 3));
    expect(onChange.mock.calls.length).toBeGreaterThanOrEqual(4);
    fireEvent.pointerUp(plus);
    const calls = onChange.mock.calls.length;
    act(() => vi.advanceTimersByTime(1000));
    expect(onChange.mock.calls.length).toBe(calls);
  });

  it('clamps a typed value to the range', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderOn(<FxValueCardStepper label="Down payment" unit="%" value={10} onChange={onChange} min={5} max={50} step={5} />);
    const box = screen.getByRole('spinbutton', { name: /Down payment/ });
    await user.clear(box);
    await user.type(box, '73');
    await user.tab();
    expect(onChange).toHaveBeenLastCalledWith(50);
  });
});

describe('segmented toggle, tabs, slider, switch', () => {
  it('a click on the chosen option of a two-option toggle flips it', async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();
    renderOn(
      <ToggleGroup type="single" value="light" onValueChange={onValueChange} aria-label="Mode">
        <ToggleGroupItem value="light">Light</ToggleGroupItem>
        <ToggleGroupItem value="dark">Dark</ToggleGroupItem>
      </ToggleGroup>,
    );
    await user.click(screen.getByRole('radio', { name: 'Light' }));
    expect(onValueChange).toHaveBeenCalledWith('dark');
    expect(nextSegmentValue(['a', 'b', 'c'], 'c')).toBe('a');
    expect(nextSegmentValue(['a', 'b', 'c'], 'a')).toBe('b');
  });

  it('tabs still switch their content', async () => {
    const user = userEvent.setup();
    renderOn(
      <Tabs defaultValue="one">
        <TabsList>
          <TabsTrigger value="one">One</TabsTrigger>
          <TabsTrigger value="two">Two</TabsTrigger>
        </TabsList>
        <TabsContent value="one">First</TabsContent>
        <TabsContent value="two">Second</TabsContent>
      </Tabs>,
    );
    expect(screen.getByRole('tablist')).toHaveAttribute('data-fx-tabs');
    await user.click(screen.getByRole('tab', { name: 'Two' }));
    expect(screen.getByText('Second')).toBeInTheDocument();
  });

  it('the slider steps by its step from the keyboard and shows a dot per step', () => {
    const onValueCommit = vi.fn();
    const { container } = renderOn(
      <Slider min={0} max={6} step={1} defaultValue={[3]} onValueCommit={onValueCommit}>
        <SliderThumb aria-label="Size" />
      </Slider>,
    );
    const thumb = screen.getByRole('slider', { name: 'Size' });
    fireEvent.keyDown(thumb, { key: 'ArrowRight' });
    expect(thumb).toHaveAttribute('aria-valuenow', '4');
    expect(onValueCommit).toHaveBeenLastCalledWith([4]);
    expect(container.querySelectorAll('[data-fx-slider] span[aria-hidden] > span')).toHaveLength(7);
  });

  it('the on/off switch keeps its role and state', async () => {
    const user = userEvent.setup();
    renderOn(<Switch aria-label="Add-on" />);
    const sw = screen.getByRole('switch', { name: 'Add-on' });
    expect(sw).toHaveAttribute('data-fx-switch');
    await user.click(sw);
    expect(sw).toHaveAttribute('aria-checked', 'true');
  });
});

describe('secrets and passwords', () => {
  it('the password eye is a pressed-state button reachable by Tab', async () => {
    const user = userEvent.setup();
    renderOn(<SecretInput aria-label="Token" defaultValue="abc" />);
    const field = screen.getByLabelText('Token');
    expect(field).toHaveAttribute('type', 'password');
    field.focus();
    await user.tab();
    const eye = screen.getByRole('button', { name: 'Show value' });
    expect(eye).toHaveFocus();
    expect(eye).toHaveAttribute('aria-pressed', 'false');
    await user.click(eye);
    expect(field).toHaveAttribute('type', 'text');
    expect(screen.getByRole('button', { name: 'Hide value' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('a new secret shows once, read-only, with Copy and the warning line', () => {
    renderOn(<FxSecretOnce label="API key" value="sk_live_a91c" />);
    const field = screen.getByRole('textbox', { name: 'API key' });
    expect(field).toHaveAttribute('readonly');
    expect(field.className).toContain('font-mono');
    expect(screen.getByRole('button', { name: 'Copy' })).toBeInTheDocument();
    expect(screen.getByText("Copy it now. It won't be shown again.")).toBeInTheDocument();
  });

  it('password strength fills its bars and names what is missing', () => {
    renderOn(<FxPasswordStrength password="abcdefg1" />);
    expect(screen.getByText('Fair')).toBeInTheDocument();
    expect(screen.getByText(/Add a capital letter/)).toBeInTheDocument();
  });
});
