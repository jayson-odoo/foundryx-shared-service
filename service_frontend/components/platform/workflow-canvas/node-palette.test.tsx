/**
 * NodePalette module-tagged filtering (plan sprint-4/17 AC-OA-20) - a
 * `module`-tagged catalog entry (the 3 omnichannel nodes) is hidden unless
 * that module is ACTIVE for the tenant; `ai_agent.run` (no module tag) is
 * always visible. Mocks `useInstalledModules` the way the palette consumes it.
 */
import { DndContext } from '@dnd-kit/core';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { NodePalette } from './node-palette';

const isActiveMock = vi.fn();

vi.mock('@/hooks/use-app-store', () => ({
  useInstalledModules: () => ({ ready: true, isActive: isActiveMock }),
}));

// Every type these tests probe - as if the backend registry already resolves
// all of them, so these pre-existing tests exercise module/permission
// gating in isolation from the B-4 registration gate (a dedicated describe
// block below tests THAT gate).
const ALL_REGISTERED = [
  'manual',
  'omnichannel.message_received',
  'omnichannel.get_contact',
  'omnichannel.send_message',
  'ai_agent.run',
  'code.run',
  'http.request',
];

function renderPalette(
  props: Partial<React.ComponentProps<typeof NodePalette>> = {},
) {
  return render(
    <DndContext onDragEnd={() => {}}>
      <NodePalette
        hasTrigger={false}
        disabled={false}
        onAdd={vi.fn()}
        registeredNodeTypes={ALL_REGISTERED}
        {...props}
      />
    </DndContext>,
  );
}

describe('NodePalette module filtering', () => {
  it('hides the omnichannel trigger + actions when the module is inactive', () => {
    isActiveMock.mockReturnValue(false);
    renderPalette();

    fireEvent.change(screen.getByTestId('palette-search'), {
      target: { value: 'omnichannel' },
    });

    expect(
      screen.queryByTestId('palette-omnichannel.message_received'),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId('palette-omnichannel.get_contact'),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId('palette-omnichannel.send_message'),
    ).not.toBeInTheDocument();
    expect(screen.getByText('No matching nodes.')).toBeInTheDocument();
  });

  it('shows the omnichannel trigger + actions once the module is active', () => {
    isActiveMock.mockReturnValue(true);
    renderPalette();

    fireEvent.change(screen.getByTestId('palette-search'), {
      target: { value: 'omnichannel' },
    });

    expect(
      screen.getByTestId('palette-omnichannel.message_received'),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId('palette-omnichannel.get_contact'),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId('palette-omnichannel.send_message'),
    ).toBeInTheDocument();
  });

  it('always shows the core ai_agent.run action regardless of module state', () => {
    isActiveMock.mockReturnValue(false);
    renderPalette();

    fireEvent.change(screen.getByTestId('palette-search'), {
      target: { value: 'ai agent' },
    });

    expect(screen.getByTestId('palette-ai_agent.run')).toBeInTheDocument();
  });

  it('disables Code when workflows.code is unavailable', () => {
    isActiveMock.mockReturnValue(true);
    renderPalette({ canCode: false });
    fireEvent.change(screen.getByTestId('palette-search'), {
      target: { value: 'code' },
    });
    expect(screen.getByTestId('palette-code.run')).toBeDisabled();
  });

  it('disables HTTP request when workflows.http is unavailable (plan 31 S3, AC-WFP-37/69)', () => {
    isActiveMock.mockReturnValue(true);
    renderPalette({ canHttp: false });
    fireEvent.change(screen.getByTestId('palette-search'), {
      target: { value: 'http request' },
    });
    expect(screen.getByTestId('palette-http.request')).toBeDisabled();
  });

  it('enables HTTP request when workflows.http is granted', () => {
    isActiveMock.mockReturnValue(true);
    renderPalette({ canHttp: true });
    fireEvent.change(screen.getByTestId('palette-search'), {
      target: { value: 'http request' },
    });
    expect(screen.getByTestId('palette-http.request')).not.toBeDisabled();
  });
});

describe('NodePalette - registeredNodeTypes gates the palette (plan 31 S3 review B-4)', () => {
  it('omits (not disables) a catalog entry with no backend ActionDef yet', () => {
    isActiveMock.mockReturnValue(true);
    // Registry does NOT resolve `omnichannel.ask_question` yet (S4).
    renderPalette({
      registeredNodeTypes: ALL_REGISTERED.filter((t) => t !== 'http.request'),
    });
    fireEvent.change(screen.getByTestId('palette-search'), {
      target: { value: 'http request' },
    });
    expect(screen.queryByTestId('palette-http.request')).not.toBeInTheDocument();
    expect(screen.getByText('No matching nodes.')).toBeInTheDocument();
  });

  it('shows nothing new before the metadata has loaded (registeredNodeTypes undefined)', () => {
    isActiveMock.mockReturnValue(true);
    renderPalette({ registeredNodeTypes: undefined });
    fireEvent.change(screen.getByTestId('palette-search'), {
      target: { value: 'ai agent' },
    });
    expect(screen.queryByTestId('palette-ai_agent.run')).not.toBeInTheDocument();
  });

  it('the IF node is always shown - it is structural, never a registry entry', () => {
    isActiveMock.mockReturnValue(true);
    renderPalette({ registeredNodeTypes: [] });
    fireEvent.change(screen.getByTestId('palette-search'), {
      target: { value: 'condition' },
    });
    expect(screen.getByTestId('palette-if')).toBeInTheDocument();
  });
});

/**
 * Plan 31 review round 2, R-2: the palette gates itself on the metadata call's
 * `registeredNodeTypes`, so a slow/failed call must never read as "this tenant
 * has no nodes" - it shows a skeleton, then an explicit failure state.
 */
describe('NodePalette catalog load state (R-2)', () => {
  it('renders a skeleton while the node catalog is loading', () => {
    isActiveMock.mockReturnValue(true);
    renderPalette({ catalogStatus: 'loading', registeredNodeTypes: undefined });

    expect(screen.getByTestId('node-palette-loading')).toBeInTheDocument();
    expect(screen.queryByTestId('node-palette')).not.toBeInTheDocument();
    expect(screen.queryByTestId('palette-search')).not.toBeInTheDocument();
  });

  it('renders an explicit failure state when the node catalog fails', () => {
    isActiveMock.mockReturnValue(true);
    renderPalette({ catalogStatus: 'error', registeredNodeTypes: undefined });

    expect(screen.getByTestId('node-palette-error')).toBeInTheDocument();
    expect(
      screen.getByText('The node catalog could not be loaded.'),
    ).toBeInTheDocument();
    expect(screen.queryByTestId('palette-manual')).not.toBeInTheDocument();
  });

  it('renders the catalog once it is ready', () => {
    isActiveMock.mockReturnValue(true);
    renderPalette({ catalogStatus: 'ready' });

    expect(screen.getByTestId('node-palette')).toBeInTheDocument();
    expect(screen.queryByTestId('node-palette-loading')).not.toBeInTheDocument();
    expect(screen.queryByTestId('node-palette-error')).not.toBeInTheDocument();
  });
});
