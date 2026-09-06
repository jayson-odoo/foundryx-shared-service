/**
 * Plan 31 (omnichannel workflow parity) palette coverage - AC-WFP-01.
 * Wait and Business hours (Logic-category actions) render in the Logic
 * section alongside the IF node, not in Actions; every new trigger/action is
 * gated by the omnichannel module the same as the existing entries.
 */
import { DndContext } from '@dnd-kit/core';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { NodePalette } from './node-palette';

const isActiveMock = vi.fn();

vi.mock('@/hooks/use-app-store', () => ({
  useInstalledModules: () => ({ ready: true, isActive: isActiveMock }),
}));

function renderPalette() {
  return render(
    <DndContext onDragEnd={() => {}}>
      <NodePalette hasTrigger={false} disabled={false} onAdd={vi.fn()} />
    </DndContext>,
  );
}

describe('NodePalette - Logic section derivation (D-A5-19)', () => {
  it('lists Wait and Business hours under Logic, not Actions, when the module is active', () => {
    isActiveMock.mockReturnValue(true);
    renderPalette();
    // Sections collapse by default (the growing catalog stays compact) -
    // expand both before asserting membership.
    fireEvent.click(screen.getByTestId('palette-section-logic'));
    fireEvent.click(screen.getByTestId('palette-section-actions'));
    const logicSection = screen.getByTestId('palette-section-logic').parentElement!;
    const actionsSection = screen.getByTestId('palette-section-actions').parentElement!;
    expect(within(logicSection).getByTestId('palette-omnichannel.wait')).toBeInTheDocument();
    expect(
      within(logicSection).getByTestId('palette-omnichannel.business_hours'),
    ).toBeInTheDocument();
    expect(within(logicSection).getByTestId('palette-if')).toBeInTheDocument();
    expect(
      within(actionsSection).queryByTestId('palette-omnichannel.wait'),
    ).not.toBeInTheDocument();
  });

  it('hides Wait and Business hours (module-tagged) when the module is inactive, keeps the IF node', () => {
    isActiveMock.mockReturnValue(false);
    renderPalette();
    fireEvent.click(screen.getByTestId('palette-section-logic'));
    const logicSection = screen.getByTestId('palette-section-logic').parentElement!;
    expect(within(logicSection).getByTestId('palette-if')).toBeInTheDocument();
    expect(
      within(logicSection).queryByTestId('palette-omnichannel.wait'),
    ).not.toBeInTheDocument();
    expect(
      within(logicSection).queryByTestId('palette-omnichannel.business_hours'),
    ).not.toBeInTheDocument();
  });

  it('finds the new triggers and steps by search once the module is active', () => {
    isActiveMock.mockReturnValue(true);
    renderPalette();
    fireEvent.change(screen.getByTestId('palette-search'), {
      target: { value: 'conversation closed' },
    });
    expect(
      screen.getByTestId('palette-omnichannel.conversation_closed'),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByTestId('palette-search'), {
      target: { value: 'ask a question' },
    });
    expect(screen.getByTestId('palette-omnichannel.ask_question')).toBeInTheDocument();

    fireEvent.change(screen.getByTestId('palette-search'), {
      target: { value: 'http request' },
    });
    expect(screen.getByTestId('palette-http.request')).toBeInTheDocument();
  });
});
