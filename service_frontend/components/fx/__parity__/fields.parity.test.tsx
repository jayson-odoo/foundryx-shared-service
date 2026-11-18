/**
 * Switch-off parity: the field primitives (see parity-utils.ts). Fixed props,
 * rendered with the Foundryx UIUX switch off (no provider = off): Textarea,
 * the bare Select, SearchSelect and MultiSelect (closed and open), the date
 * field, Calendar, DateRangePicker, ToggleGroup, Tabs, Slider, Switch and
 * SecretInput, plus the strings the datetime hook and the money formatter
 * give today.
 */
import { act, render, renderHook, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CalendarDate } from '@internationalized/date';
import { describe, expect, it, vi } from 'vitest';
import { Textarea } from '@/components/ui/textarea';
// The bare Select is pinned here because a few existing screens still use it.
// eslint-disable-next-line no-restricted-imports
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { DateField, DateInput } from '@/components/ui/datefield';
import { Calendar } from '@/components/ui/calendar';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Slider, SliderThumb } from '@/components/ui/slider';
import { Switch } from '@/components/ui/switch';
import { SearchSelect } from '@/components/platform/search-select';
import { MultiSelect } from '@/components/platform/multi-select';
import { DateRangePicker } from '@/components/platform/date-range-picker';
import { SecretInput } from '@/components/platform/secret-input';
import { useDatetime } from '@/hooks/use-datetime';
import { formatMoney } from '@/lib/money';
import { parityHtml as sharedParityHtml } from './parity-utils';

/**
 * Two more normalisations for this file only (the shared helper stays as it
 * is, so the other snapshots are untouched): React 19.2's `_r_3_` ids are
 * renamed in order of first appearance, so running a subset of the tests
 * cannot shift them, and the date input's own en dash in an aria value text
 * ("11 - November") is written as a hyphen, since the repo bans the en dash
 * from every tracked file. An open popover's opening animation leaves an
 * inline opacity/transform that depends on timing, so that style is dropped.
 */
function parityHtml(root: Element): string {
  const seen = new Map<string, string>();
  return sharedParityHtml(root)
    .replace(/_r_[0-9a-z]+_/g, (id) => {
      let stable = seen.get(id);
      if (!stable) {
        stable = `_id${seen.size}_`;
        seen.set(id, stable);
      }
      return stable;
    })
    .replace(/\u2013/g, '-')
    .replace(/ style="opacity: [\d.]+; transform: [^"]*;"/g, '');
}

vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { timezone: 'Asia/Kuala_Lumpur' } },
    status: 'authenticated',
  }),
}));

const OPTIONS = [
  { label: 'Alpha', value: 'a' },
  { label: 'Beta', value: 'b' },
  { label: 'Gamma', value: 'c' },
];

describe('parity (switch off): Textarea', () => {
  it('renders the sizes and states as before', () => {
    const { container } = render(
      <div>
        <Textarea placeholder="Note" defaultValue="Hello" />
        <Textarea variant="sm" />
        <Textarea variant="lg" aria-invalid="true" />
        <Textarea disabled defaultValue="locked" />
      </div>,
    );
    expect(parityHtml(container)).toMatchSnapshot();
  });
});

describe('parity (switch off): Select', () => {
  it('renders the closed trigger as before', () => {
    const { container } = render(
      <Select defaultValue="b">
        <SelectTrigger aria-label="Pick">
          <SelectValue placeholder="Pick one" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="a">Alpha</SelectItem>
          <SelectItem value="b">Beta</SelectItem>
        </SelectContent>
      </Select>,
    );
    expect(parityHtml(container)).toMatchSnapshot();
  });
});

describe('parity (switch off): SearchSelect', () => {
  it('renders closed and open as before', async () => {
    const user = userEvent.setup();
    const { container, baseElement } = render(
      <SearchSelect
        options={OPTIONS}
        value="b"
        onChange={() => {}}
        ariaLabel="Letter"
      />,
    );
    expect(parityHtml(container)).toMatchSnapshot();
    await user.click(screen.getByRole('combobox', { name: 'Letter' }));
    expect(parityHtml(baseElement)).toMatchSnapshot();
  });
});

describe('parity (switch off): MultiSelect', () => {
  it('renders closed and open as before', async () => {
    const user = userEvent.setup();
    const { container, baseElement } = render(
      <MultiSelect options={OPTIONS} value={['a', 'c']} onChange={() => {}} />,
    );
    expect(parityHtml(container)).toMatchSnapshot();
    await user.click(screen.getByRole('combobox'));
    expect(parityHtml(baseElement)).toMatchSnapshot();
  });
});

describe('parity (switch off): DateField', () => {
  it('renders the segmented date input as before', () => {
    const { container } = render(
      <DateField
        aria-label="Due"
        defaultValue={new CalendarDate(2026, 11, 14)}
      >
        <DateInput />
      </DateField>,
    );
    expect(parityHtml(container)).toMatchSnapshot();
  });
});

describe('parity (switch off): Calendar', () => {
  it('renders a fixed month as before', () => {
    const { container } = render(
      <Calendar
        mode="single"
        month={new Date(2026, 10, 1)}
        today={new Date(2026, 10, 18)}
        selected={new Date(2026, 10, 14)}
      />,
    );
    expect(parityHtml(container)).toMatchSnapshot();
  });
});

describe('parity (switch off): DateRangePicker', () => {
  it('renders the closed picker as before', () => {
    const { container } = render(
      <DateRangePicker
        value={{ preset: 'custom', from: '2026-11-01', to: '2026-11-30' }}
        onChange={() => {}}
        timeZone="Asia/Kuala_Lumpur"
      />,
    );
    expect(parityHtml(container)).toMatchSnapshot();
  });
});

describe('parity (switch off): ToggleGroup', () => {
  it('renders single and outline groups as before', () => {
    const { container } = render(
      <div>
        <ToggleGroup type="single" variant="outline" value="dark">
          <ToggleGroupItem value="light">Light</ToggleGroupItem>
          <ToggleGroupItem value="dark">Dark</ToggleGroupItem>
        </ToggleGroup>
        <ToggleGroup type="multiple" defaultValue={['b']}>
          <ToggleGroupItem value="a">A</ToggleGroupItem>
          <ToggleGroupItem value="b">B</ToggleGroupItem>
        </ToggleGroup>
      </div>,
    );
    expect(parityHtml(container)).toMatchSnapshot();
  });
});

describe('parity (switch off): Tabs', () => {
  it('renders line and default lists as before', () => {
    const { container } = render(
      <div>
        <Tabs defaultValue="one">
          <TabsList>
            <TabsTrigger value="one">One</TabsTrigger>
            <TabsTrigger value="two">Two</TabsTrigger>
          </TabsList>
          <TabsContent value="one">First</TabsContent>
          <TabsContent value="two">Second</TabsContent>
        </Tabs>
        <Tabs defaultValue="b">
          <TabsList variant="button" size="sm">
            <TabsTrigger value="a">A</TabsTrigger>
            <TabsTrigger value="b">B</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>,
    );
    expect(parityHtml(container)).toMatchSnapshot();
  });
});

describe('parity (switch off): Slider', () => {
  it('renders as before', () => {
    const { container } = render(
      <Slider min={0} max={6} step={1} defaultValue={[3]} aria-label="Size">
        <SliderThumb aria-label="Size" />
      </Slider>,
    );
    expect(parityHtml(container)).toMatchSnapshot();
  });
});

describe('parity (switch off): Switch', () => {
  it('renders on, off and disabled as before', () => {
    const { container } = render(
      <div>
        <Switch aria-label="On" defaultChecked />
        <Switch aria-label="Off" size="sm" />
        <Switch aria-label="Locked" disabled />
      </div>,
    );
    expect(parityHtml(container)).toMatchSnapshot();
  });
});

describe('parity (switch off): SecretInput', () => {
  it('renders hidden and revealed as before', async () => {
    const user = userEvent.setup();
    const { container } = render(
      <SecretInput aria-label="Token" defaultValue="sk_live_a91c" />,
    );
    expect(parityHtml(container)).toMatchSnapshot();
    await user.click(screen.getByRole('button', { name: 'Show value' }));
    expect(parityHtml(container)).toMatchSnapshot();
  });
});

describe('parity (switch off): datetime and money strings', () => {
  it('formats moments as before', () => {
    const { result } = renderHook(() => useDatetime());
    const iso = '2026-11-14T06:14:00Z';
    let out: Record<string, string> = {};
    act(() => {
      out = {
        timeZone: result.current.timeZone,
        date: result.current.formatDate(iso),
        dateTime: result.current.formatDateTime(iso),
        time: result.current.formatTime(iso),
        dmyDateTime: result.current.formatDmyDateTime(iso),
        dmyDate: result.current.formatDmyDate(iso),
        none: result.current.formatDateTime(null),
      };
    });
    expect(out).toMatchSnapshot();
  });

  it('formats money as before', () => {
    expect([
      formatMoney(1234.5, 'MYR'),
      formatMoney(1234.5, 'SGD'),
      formatMoney(1234, 'JPY'),
      formatMoney(-12, 'USD', 2),
      formatMoney(null, 'MYR'),
    ]).toMatchSnapshot();
  });
});
