import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { WizardContext, WizardSource } from '@/types/lead-capture-wizard';

const svc = vi.hoisted(() => ({
  redeem: vi.fn(),
  context: vi.fn(),
  login: vi.fn(),
  pages: vi.fn(),
  connect: vi.fn(),
  source: vi.fn(),
  forms: vi.fn(),
  saveForms: vi.fn(),
  fields: vi.fn(),
  questions: vi.fn(),
  saveFieldMap: vi.fn(),
  sendTestLead: vi.fn(),
  lastTestLead: vi.fn(),
  finish: vi.fn(),
  googleSource: vi.fn(),
}));
vi.mock('@/services/lead-capture-wizard-service', () => ({ leadCaptureWizardService: svc }));

import { useLeadCaptureWizard } from './use-lead-capture-wizard';

const LIVE: WizardSource = {
  id: 'src',
  platform: 'facebook',
  name: 'Home',
  status: 'LIVE',
  pageId: '1',
  pageName: 'Home',
  formsMode: 'all',
  formIds: [],
  needsMapping: [],
  fieldMap: { f1: { q: 'name' } },
  lastLeadAt: null,
  createdAt: '2026-11-17T00:00:00Z',
};

const CONTEXT: WizardContext = {
  branding: { name: 'Acme', logoUrl: null },
  channels: [{ key: 'facebook', label: 'Facebook', setup: 'automatic' }],
  login: { available: true, simulated: true, appId: null, configId: null, graphVersion: 'v25.0', scopes: [] },
  returnOrigin: 'https://crm.example.com',
  source: LIVE,
};

async function openReconnected() {
  window.history.replaceState(null, '', '/public/lead-capture/connect#s=secret-value-0123456789abcdef');
  svc.redeem.mockResolvedValue({ accessToken: 't', expiresAt: '2999-01-01T00:00:00Z', returnOrigin: null, sourceId: 'src' });
  svc.context.mockResolvedValue(CONTEXT);
  svc.login.mockResolvedValue([{ id: '1', name: 'Home' }]);
  svc.connect.mockResolvedValue(LIVE);
  svc.forms.mockResolvedValue({ formsMode: 'all', formIds: [], tosAccepted: true, data: [{ id: 'f1', name: 'F1', status: 'ACTIVE', createdAt: null }, { id: 'f2', name: 'F2', status: 'ACTIVE', createdAt: null }] });
  const hook = renderHook(() => useLeadCaptureWizard());
  await waitFor(() => expect(hook.result.current.phase).toBe('ready'));
  await act(() => hook.result.current.signIn());
  await act(() => hook.result.current.connectPage());
  return hook;
}

describe('useLeadCaptureWizard', () => {
  beforeEach(() => {
    vi.useRealTimers();
    Object.values(svc).forEach((fn) => fn.mockReset());
    window.sessionStorage.clear();
  });
  afterEach(() => vi.useRealTimers());

  it('removes the URL secret and opens the session once', async () => {
    const hook = await openReconnected();
    expect(window.location.hash).toBe('');
    expect(svc.redeem).toHaveBeenCalledTimes(1);
    expect(hook.result.current.source?.fieldMap).toEqual({ f1: { q: 'name' } });
  });

  it('a reconnected LIVE source passes the test only on a NEW test lead', async () => {
    const hook = await openReconnected();
    svc.lastTestLead.mockResolvedValue({ leadId: 'old', receivedAt: '2026-11-01T00:00:00Z' });
    svc.sendTestLead.mockResolvedValue(undefined);
    vi.useFakeTimers();
    await act(async () => {
      await hook.result.current.setTestFormId('f1');
    });
    await act(() => hook.result.current.sendTestLead());
    expect(hook.result.current.state.testPassed).toBe(false);
    expect(hook.result.current.testWaiting).toBe(true);
    svc.lastTestLead.mockResolvedValue({ leadId: 'new', receivedAt: '2026-11-17T00:00:00Z' });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3100);
    });
    expect(hook.result.current.state.testPassed).toBe(true);
  });

  it('stops polling once the wizard unmounts', async () => {
    const hook = await openReconnected();
    svc.lastTestLead.mockResolvedValue({ leadId: 'old', receivedAt: null });
    vi.useFakeTimers();
    act(() => hook.result.current.setTestFormId('f1'));
    await act(() => hook.result.current.sendTestLead());
    const calls = svc.lastTestLead.mock.calls.length;
    hook.unmount();
    await vi.advanceTimersByTimeAsync(20000);
    expect(svc.lastTestLead.mock.calls.length).toBe(calls);
  });

  it('switches the mapped form only after its questions arrived', async () => {
    const hook = await openReconnected();
    svc.questions.mockRejectedValueOnce(new Error('down'));
    await act(() => hook.result.current.chooseMapForm('f2'));
    expect(hook.result.current.mapFormId).not.toBe('f2');
    svc.questions.mockResolvedValueOnce({ formId: 'f2', formName: 'F2', data: [] });
    await act(() => hook.result.current.chooseMapForm('f2'));
    expect(hook.result.current.mapFormId).toBe('f2');
  });

  it('copies the Google URL and key on a plain-http page (no navigator.clipboard) and unblocks Continue', async () => {
    window.history.replaceState(null, '', '/public/lead-capture/connect#s=secret-value-0123456789abcdef');
    svc.redeem.mockResolvedValue({ accessToken: 't', expiresAt: '2999-01-01T00:00:00Z', returnOrigin: null, sourceId: null });
    svc.context.mockResolvedValue({ ...CONTEXT, source: null });
    svc.googleSource.mockResolvedValue({ source: { ...LIVE, platform: 'google' }, url: 'http://host/in/abc', key: 'k3y' });
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true });
    const exec = vi.fn(() => true);
    Object.defineProperty(document, 'execCommand', { value: exec, configurable: true });
    const hook = renderHook(() => useLeadCaptureWizard());
    await waitFor(() => expect(hook.result.current.phase).toBe('ready'));
    act(() => hook.result.current.chooseChannel('google'));
    await waitFor(() => expect(hook.result.current.state.guided).not.toBeNull());
    await act(() => hook.result.current.copyGuided('url'));
    await act(() => hook.result.current.copyGuided('key'));
    expect(hook.result.current.problem).toBeNull();
    expect(hook.result.current.state.copiedUrl).toBe(true);
    expect(hook.result.current.state.copiedKey).toBe(true);
    expect(exec).toHaveBeenCalledTimes(2);
  });
});
