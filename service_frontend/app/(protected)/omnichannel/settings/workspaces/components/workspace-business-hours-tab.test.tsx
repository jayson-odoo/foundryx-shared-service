import { render, screen } from '@testing-library/react';
import { createRef } from 'react';
import { describe, expect, it, vi } from 'vitest';

import type { BusinessHoursWindows } from '@/types/omnichannel';
import {
  WorkspaceBusinessHoursTab,
  type BusinessHoursController,
} from './workspace-business-hours-tab';

const { useBusinessHoursMock } = vi.hoisted(() => ({ useBusinessHoursMock: vi.fn() }));
vi.mock('./use-business-hours', () => ({ useBusinessHours: useBusinessHoursMock }));

function emptyWindows(): BusinessHoursWindows {
  return { mon: [], tue: [], wed: [], thu: [], fri: [], sat: [], sun: [] };
}

function base(over: Partial<ReturnType<typeof useBusinessHoursMock>> = {}) {
  return {
    isLoading: false,
    loadError: null,
    timezone: 'Asia/Kuala_Lumpur',
    windows: { ...emptyWindows(), mon: [{ from: '09:00', to: '18:00' }] },
    isDirty: false,
    isSaving: false,
    saveError: null,
    fieldErrors: {},
    setTimezone: vi.fn(),
    setWindows: vi.fn(),
    save: vi.fn(async () => true),
    discard: vi.fn(),
    ...over,
  };
}

describe('WorkspaceBusinessHoursTab', () => {
  it('shows a create-first placeholder while creating', () => {
    useBusinessHoursMock.mockReturnValue(base());
    render(<WorkspaceBusinessHoursTab workspaceId={null} creating editing={false} />);
    expect(screen.getByText(/after creating the workspace/i)).toBeInTheDocument();
  });

  it('renders the read view: a configured window and "Closed" for empty days', () => {
    useBusinessHoursMock.mockReturnValue(base());
    render(<WorkspaceBusinessHoursTab workspaceId="wsp-001" creating={false} editing={false} />);
    expect(screen.getByText('09:00 - 18:00')).toBeInTheDocument();
    expect(screen.getAllByText('Closed').length).toBeGreaterThan(0);
    // Read-only: no time inputs, no add-window buttons.
    expect(screen.queryByTestId('business-hours-add-mon')).not.toBeInTheDocument();
  });

  it('renders a failure state (no Save possible) when the load fails', () => {
    useBusinessHoursMock.mockReturnValue(
      base({ loadError: 'Business hours could not be loaded.' }),
    );
    render(<WorkspaceBusinessHoursTab workspaceId="wsp-001" creating={false} editing />);
    expect(screen.getByTestId('business-hours-load-error')).toHaveTextContent(
      'Business hours could not be loaded.',
    );
    // No editable schedule is rendered - nothing to accidentally Save over.
    expect(screen.queryByTestId('business-hours-schedule')).not.toBeInTheDocument();
  });

  it('renders time inputs and an Add window button per day while editing', () => {
    useBusinessHoursMock.mockReturnValue(base());
    render(<WorkspaceBusinessHoursTab workspaceId="wsp-001" creating={false} editing />);
    expect(screen.getByLabelText('Monday window 1 start')).toHaveValue('09:00');
    expect(screen.getByLabelText('Monday window 1 end')).toHaveValue('18:00');
    expect(screen.getByTestId('business-hours-add-mon')).toBeInTheDocument();
    expect(screen.getByTestId('business-hours-add-sun')).toBeInTheDocument();
  });

  it('shows a per-window 422 field error (from === to)', () => {
    useBusinessHoursMock.mockReturnValue(
      base({ fieldErrors: { 'windows.mon.0': 'End time must differ from the start time.' } }),
    );
    render(<WorkspaceBusinessHoursTab workspaceId="wsp-001" creating={false} editing />);
    expect(screen.getByTestId('business-hours-error-windows.mon.0')).toHaveTextContent(
      'End time must differ from the start time.',
    );
  });

  it('propagates isDirty to onDirtyChange', () => {
    useBusinessHoursMock.mockReturnValue(base({ isDirty: true }));
    const onDirtyChange = vi.fn();
    render(
      <WorkspaceBusinessHoursTab
        workspaceId="wsp-001"
        creating={false}
        editing
        onDirtyChange={onDirtyChange}
      />,
    );
    expect(onDirtyChange).toHaveBeenCalledWith(true);
  });

  it('wires save/discard onto the imperative controller ref', () => {
    const saveMock = vi.fn(async () => true);
    const discardMock = vi.fn();
    useBusinessHoursMock.mockReturnValue(base({ save: saveMock, discard: discardMock }));
    const controller = createRef<BusinessHoursController | null>();
    render(
      <WorkspaceBusinessHoursTab
        workspaceId="wsp-001"
        creating={false}
        editing
        controller={controller}
      />,
    );
    expect(controller.current?.save).toBe(saveMock);
    expect(controller.current?.discard).toBe(discardMock);
  });
});
