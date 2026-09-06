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

function renderPalette(
  props: Partial<React.ComponentProps<typeof NodePalette>> = {},
) {
  return render(
    <DndContext onDragEnd={() => {}}>
      <NodePalette
        hasTrigger={false}
        disabled={false}
        onAdd={vi.fn()}
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
