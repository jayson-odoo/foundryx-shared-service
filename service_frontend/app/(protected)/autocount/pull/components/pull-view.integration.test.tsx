/**
 * Integration test (sprint-5/10 S2, browser round 1 defect 3): the browser
 * run found `/autocount/pull` completely empty and non-functional even
 * though every unit test in this directory passed - because those tests all
 * `vi.mock('@/services/autocount-service', ...)` wholesale, which proves the
 * COMPONENT's own logic but never proves the production WIRING (`PullView`
 * -> `use-pull-list-config`/`use-autocount-pull` -> the real `autocountService`
 * singleton `withPhase1PullMock(realAutocountService)` exported by
 * `services/autocount-service.ts`).
 *
 * This suite renders `PullView` against that REAL singleton (no service-level
 * mock at all - only `@/lib/api-client` is stubbed, so `realAutocountService`
 * never hits the network) and only stubs the heavy `ResourceList` DataGrid
 * shell (the same house pattern `staged-records-list.test.tsx` already uses),
 * so the actual defect - empty fixtures, a mutation that didn't reach the
 * list - would have failed here from day one.
 */
import { useEffect, useState } from 'react';
import { fireEvent, render as rtlRender, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import type { ListQuery, ListResult } from '@/types/resource';
import type { AutocountPullListRow } from './pull-row';
import type { ResourceListConfig } from '@/components/platform/resource-list';

function render(ui: React.ReactElement) {
  return rtlRender(<SettingsProvider>{ui}</SettingsProvider>);
}

const apiFetchMock = vi.fn((path: string) => {
  if (path.startsWith('/autocount/companies?')) {
    // The lane's REAL backend company list - empty here on purpose: the
    // fixture company `withPhase1PullMock` appends is what must carry the
    // Keys/Snapshots surfaces in this phase, not a live company.
    return Promise.resolve({ data: [], total: 0, page: 0 });
  }
  return Promise.reject(new Error(`unexpected apiFetch call in this suite: ${path}`));
});
vi.mock('@/lib/api-client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api-client')>();
  return {
    ...actual,
    apiFetch: (...args: Parameters<typeof actual.apiFetch>) => apiFetchMock(...args),
  };
});

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), prefetch: vi.fn() }),
}));

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    timeZone: 'UTC',
    formatDate: (v: string) => v ?? '',
    formatDateTime: (v: string) => v ?? '',
    formatTime: (v: string) => v ?? '',
  }),
}));

// The DataGrid shell is exercised elsewhere (every other `use-pull-list-
// config` test); this suite proves the WIRING, so it stands in with a tiny
// fetcher-driven list + a "create" button standing in for the shell's own.
vi.mock('@/components/platform/resource-list', () => ({
  ResourceList: ({ config }: { config: ResourceListConfig<AutocountPullListRow> }) => {
    const [rows, setRows] = useState<AutocountPullListRow[]>([]);
    useEffect(() => {
      let cancelled = false;
      const query: ListQuery = { page: 0, pageSize: 25, segment: 'keys' };
      config
        .fetcher(query)
        .then((result: ListResult<AutocountPullListRow>) => {
          if (!cancelled) setRows(result.data);
        })
        .catch(() => undefined);
      return () => {
        cancelled = true;
      };
    }, [config]);
    return (
      <div>
        <button onClick={() => config.onCreate?.()}>{config.createLabel}</button>
        <ul>
          {rows.map((r) => (
            <li key={r.id}>
              {r.kind === 'key' ? `${r.name} ${r.revokedAt ? '(revoked)' : '(active)'}` : r.id}
            </li>
          ))}
        </ul>
      </div>
    );
  },
}));

// Same stub `issue-key-dialog.test.tsx` already established for a
// MultiSelect nested inside a Dialog - the popover internals aren't under
// test here.
vi.mock('@/components/platform/multi-select', () => ({
  MultiSelect: ({
    options,
    value,
    onChange,
  }: {
    options: { label: string; value: string }[];
    value: string[];
    onChange: (v: string[]) => void;
  }) => (
    <div>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() =>
            onChange(value.includes(o.value) ? value.filter((x) => x !== o.value) : [...value, o.value])
          }
        >
          {`toggle ${o.label}`}
        </button>
      ))}
    </div>
  ),
}));

const { PullView } = await import('./pull-view');

describe('PullView wired to the REAL autocountService singleton (browser round 1 defect 3)', () => {
  it('the Keys segment shows the seeded fixture rows on first render (no click needed)', async () => {
    render(<PullView />);
    await waitFor(() => expect(screen.getByText('Sorento production (active)')).toBeInTheDocument());
    expect(screen.getByText('Old staging key (revoked)')).toBeInTheDocument();
  });

  it('Issue key, through the REAL hook + service, reveals the plaintext once AND the list refetches with the new row', async () => {
    render(<PullView />);
    await waitFor(() => expect(screen.getByText('Sorento production (active)')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: 'Issue key' }));
    await waitFor(() => expect(screen.getByLabelText('Name')).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Browser round 1 key' } });
    // The fixture company `withPhase1PullMock` appends (no real company in
    // this suite's stubbed backend) - proves the Build/Issue pickers are no
    // longer stuck on an empty real company list either.
    fireEvent.click(screen.getByText('toggle Pull demo (mock)'));
    fireEvent.click(screen.getByRole('button', { name: 'Issue key' }));

    const plaintextInput = await screen.findByLabelText('Plaintext key');
    expect((plaintextInput as HTMLInputElement).value).toMatch(/^fxa_live_/);
    expect(screen.getByText(/will not be shown again/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    await waitFor(() =>
      expect(screen.getByText('Browser round 1 key (active)')).toBeInTheDocument(),
    );
  });
});
