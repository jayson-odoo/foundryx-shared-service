import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api-client';
import { brWithBuild, buildInfo } from './br-build-fixtures';
import { useBrBuild } from './use-br-build';

const sendToBuild = vi.fn();
vi.mock('@/services/business-requirement-service', () => ({
  businessRequirementService: { sendToBuild: (...a: unknown[]) => sendToBuild(...a) },
}));

const can = vi.hoisted(() => vi.fn());
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: (k: string) => can(k), ready: true, permissions: new Set<string>() }),
}));

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock('@/lib/toast', () => ({ toast }));

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    timeZone: 'UTC',
    formatDate: (v: string) => v ?? '',
    formatDateTime: (v: string) => `FMT(${v})`,
    formatTime: (v: string) => v ?? '',
  }),
}));

const PERM = 'ideation.business_requirements.send_to_build';

beforeEach(() => {
  sendToBuild.mockReset();
  toast.success.mockReset();
  toast.error.mockReset();
  can.mockReset().mockImplementation((k: string) => k === PERM);
});

describe('useBrBuild header states (AC-STB-07)', () => {
  it('AC-STB-07 sendable: enabled "Send to build" whose onRun opens the confirm', () => {
    const { result } = renderHook(() =>
      useBrBuild(brWithBuild(buildInfo({ canSend: true })), { onChanged: vi.fn() }),
    );
    expect(result.current.primaryAction?.label).toBe('Send to build');
    expect(result.current.primaryAction?.disabled).toBeFalsy();
    expect(result.current.confirmOpen).toBe(false);
    act(() => {
      void result.current.primaryAction?.onRun?.();
    });
    expect(result.current.confirmOpen).toBe(true);
    act(() => result.current.closeConfirm());
    expect(result.current.confirmOpen).toBe(false);
  });

  it('AC-STB-07 blocked: disabled button and the first blocker as the actions note', () => {
    const { result } = renderHook(() =>
      useBrBuild(
        brWithBuild(
          buildInfo({ canSend: false, blockers: ['Missing: Success metric, Constraints', 'Other'] }),
        ),
        { onChanged: vi.fn() },
      ),
    );
    expect(result.current.primaryAction?.label).toBe('Send to build');
    expect(result.current.primaryAction?.disabled).toBe(true);
    expect(JSON.stringify(result.current.actionsNote)).toContain('Missing: Success metric, Constraints');
    expect(JSON.stringify(result.current.actionsNote)).not.toContain('Other');
  });

  it('AC-STB-07 sent: issue-link chip (href) and a "Sent <time> by <name>" note', () => {
    const { result } = renderHook(() =>
      useBrBuild(
        brWithBuild(
          buildInfo({
            state: 'sent',
            canSend: false,
            issueNumber: 1402,
            issueUrl: 'https://github.com/jayson-odoo/sorento-crm/issues/1402',
            sentAt: '2026-09-30T08:00:00Z',
            sentBy: { id: 'u1', name: 'Aisha' },
          }),
          { status: 'sent_to_build' },
        ),
        { onChanged: vi.fn() },
      ),
    );
    expect(result.current.primaryAction?.label).toBe('sorento-crm #1402');
    expect(result.current.primaryAction?.href).toBe(
      'https://github.com/jayson-odoo/sorento-crm/issues/1402',
    );
    const note = JSON.stringify(result.current.actionsNote);
    expect(note).toContain('Sent');
    expect(note).toContain('Aisha');
    expect(note).toContain('FMT(2026-09-30T08:00:00Z)');
  });

  it('AC-STB-07 no send_to_build permission: no primaryAction (plain Edit stays)', () => {
    can.mockReturnValue(false);
    const { result } = renderHook(() =>
      useBrBuild(brWithBuild(buildInfo({ canSend: true })), { onChanged: vi.fn() }),
    );
    expect(result.current.primaryAction).toBeUndefined();
  });
});

describe('useBrBuild.confirmSend (AC-STB-08)', () => {
  it('AC-STB-08 calls sendToBuild once even when invoked twice quickly, then onChanged + success toast', async () => {
    let resolve!: (v: unknown) => void;
    sendToBuild.mockReturnValue(new Promise((r) => (resolve = r)));
    const onChanged = vi.fn();
    const { result } = renderHook(() =>
      useBrBuild(brWithBuild(buildInfo({ canSend: true })), { onChanged }),
    );
    const sent = brWithBuild(buildInfo({ state: 'sent', issueNumber: 1402 }), {
      status: 'sent_to_build',
    });
    await act(async () => {
      void result.current.confirmSend();
      void result.current.confirmSend();
    });
    expect(sendToBuild).toHaveBeenCalledTimes(1);
    expect(sendToBuild).toHaveBeenCalledWith('br-1');
    expect(result.current.pending).toBe(true);
    await act(async () => resolve(sent));
    expect(onChanged).toHaveBeenCalledWith(sent);
    expect(toast.success).toHaveBeenCalledTimes(1);
    expect(result.current.pending).toBe(false);
  });

  it('AC-STB-08 a 422 toasts detail.message and does not call onChanged', async () => {
    sendToBuild.mockRejectedValue(
      new ApiError('Unprocessable', 422, null, {
        message: 'Complete the requirement first',
        blockers: ['Missing: Success metric'],
      }),
    );
    const onChanged = vi.fn();
    const { result } = renderHook(() =>
      useBrBuild(brWithBuild(buildInfo({ canSend: true })), { onChanged }),
    );
    await act(async () => {
      await result.current.confirmSend();
    });
    expect(toast.error).toHaveBeenCalledWith('Complete the requirement first');
    expect(onChanged).not.toHaveBeenCalled();
    expect(result.current.pending).toBe(false);
  });
});
