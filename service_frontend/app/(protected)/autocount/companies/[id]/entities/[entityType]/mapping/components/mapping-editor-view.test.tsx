import type { ReactNode } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ResourceFormConfig } from '@/components/platform/resource-form';
import type { AutocountMappingRow, AutocountMappingView } from '@/types/autocount';

/**
 * `MappingEditorView`'s "Reset to preset" ActionMenu gating (sprint-5/12,
 * Group B - AC-12-21). `ResourceForm` is reduced to "render the visible
 * actions" (the shell's own permission/visibility filtering + the
 * `!editing` gate are covered by `resource-form`'s own suite) - the point
 * here is what THIS view puts into `config.actions`: `hasPreset` AND the
 * manage permission both gate the item, and clicking it opens the dialog.
 */

const push = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));
vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

let canManage = true;
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({
    can: (key: string) => (key === 'autocount.companies.manage' ? canManage : true),
    ready: true,
  }),
}));

vi.mock('@/components/common/container', () => ({
  Container: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));
vi.mock('react-hook-form', () => ({ useForm: () => ({}) }));
vi.mock('@/components/ui/form', () => ({ Form: ({ children }: { children: ReactNode }) => <>{children}</> }));

vi.mock('./mapping-reset-dialog', () => ({
  MappingResetDialog: ({ open }: { open: boolean }) =>
    open ? <div data-testid="reset-dialog-open" /> : null,
}));

vi.mock('@/components/platform/resource-form', () => ({
  ResourceForm: ({ config }: { config: ResourceFormConfig<AutocountMappingRow> }) => (
    <div>
      {config.actions
        .filter((a) => (!a.permission || canManage) && (!a.isVisible || a.isVisible([])))
        .map((a) => (
          <button
            key={a.id}
            type="button"
            onClick={() => (a as { run: (rows: [], runtime: { reload: () => void }) => void }).run([], { reload: () => {} })}
          >
            {typeof a.label === 'function' ? a.label([]) : a.label}
          </button>
        ))}
    </div>
  ),
}));

const viewBox = vi.hoisted(() => ({ current: null as AutocountMappingView | null }));
vi.mock('@/hooks/use-autocount-mapping', () => ({
  useAutocountMapping: () => ({
    view: viewBox.current,
    isLoading: false,
    notFound: false,
    saveError: null,
    save: vi.fn(),
    testFormula: vi.fn(),
    simulate: vi.fn(),
    reload: vi.fn(),
  }),
}));
vi.mock('@/hooks/use-autocount-company', () => ({
  useAutocountCompany: () => ({ detail: null, isLoading: false, notFound: false, reload: vi.fn() }),
}));

const { MappingEditorView } = await import('./mapping-editor-view');

function view(overrides: Partial<AutocountMappingView> = {}): AutocountMappingView {
  return {
    entityType: 'product',
    rows: [],
    sorentoFields: [],
    acFields: [],
    lineSorentoFields: [],
    lineAcFields: [],
    hasPreset: false,
    ...overrides,
  };
}

describe('MappingEditorView - Reset to preset gating (sprint-5/12, AC-12-21)', () => {
  it('hidden when the entity has no preset (foolproof-UI)', () => {
    viewBox.current = view({ hasPreset: false });
    canManage = true;
    render(<MappingEditorView companyId="c1" entityType="product" />);
    expect(screen.queryByText('Reset to preset')).not.toBeInTheDocument();
  });

  it('shown when the operator holds the manage permission AND the entity has a preset', () => {
    viewBox.current = view({ hasPreset: true });
    canManage = true;
    render(<MappingEditorView companyId="c1" entityType="product" />);
    expect(screen.getByText('Reset to preset')).toBeInTheDocument();
  });

  it('hidden without the manage permission even when a preset exists', () => {
    viewBox.current = view({ hasPreset: true });
    canManage = false;
    render(<MappingEditorView companyId="c1" entityType="product" />);
    expect(screen.queryByText('Reset to preset')).not.toBeInTheDocument();
  });

  it('clicking the action opens the reset dialog', () => {
    viewBox.current = view({ hasPreset: true });
    canManage = true;
    render(<MappingEditorView companyId="c1" entityType="product" />);
    fireEvent.click(screen.getByText('Reset to preset'));
    expect(screen.getByTestId('reset-dialog-open')).toBeInTheDocument();
  });
});
