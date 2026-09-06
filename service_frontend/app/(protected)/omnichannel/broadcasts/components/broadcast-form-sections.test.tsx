/**
 * Template picker filtering (tester defect D-6, plan 29 review round 1,
 * AC-BRD-52/AC-BRD-06) - `useApprovedTemplates` is the ONE filter behind
 * the Message section's template `SearchSelect`: only APPROVED templates,
 * and only ones whose header is TEXT-or-none (a media-header template
 * needs per-send header bytes uploaded by id, D-A4-6, deferred BL-SS-083 -
 * offering one in the picker would guarantee a later send-time failure,
 * a foolproof-UI violation).
 */
import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { WhatsAppTemplate } from '@/types/omnichannel';
import { useApprovedTemplates } from './broadcast-form-sections';

const listTemplatesMock = vi.fn();
vi.mock('@/services/conversation-service', () => ({
  conversationService: {
    listTemplates: (...args: unknown[]) => listTemplatesMock(...args),
  },
}));

function template(overrides: Partial<WhatsAppTemplate> = {}): WhatsAppTemplate {
  return {
    id: 'tpl-1',
    channelId: 'chn-1',
    name: 'booking_update',
    language: 'en',
    category: 'UTILITY',
    bodyText: 'Hi {{1}}, update: {{2}}.',
    variableCount: 2,
    headerFormat: null,
    headerVariableCount: 0,
    buttonVariableCount: 0,
    status: 'APPROVED',
    ...overrides,
  };
}

describe('useApprovedTemplates', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('excludes a non-approved (PENDING) template', async () => {
    listTemplatesMock.mockResolvedValueOnce([
      template({ id: 'tpl-approved', status: 'APPROVED' }),
      template({ id: 'tpl-pending', name: 'promo_blast', status: 'PENDING' }),
    ]);
    const { result } = renderHook(() => useApprovedTemplates('chn-1'));
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.map((t) => t.id)).toEqual(['tpl-approved']);
  });

  it('excludes an APPROVED template with a media header (IMAGE/VIDEO/DOCUMENT)', async () => {
    listTemplatesMock.mockResolvedValueOnce([
      template({ id: 'tpl-text-header', headerFormat: 'TEXT' }),
      template({ id: 'tpl-no-header', headerFormat: null }),
      template({ id: 'tpl-image-header', headerFormat: 'IMAGE' }),
      template({ id: 'tpl-video-header', headerFormat: 'VIDEO' }),
      template({ id: 'tpl-document-header', headerFormat: 'DOCUMENT' }),
    ]);
    const { result } = renderHook(() => useApprovedTemplates('chn-1'));
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.map((t) => t.id).sort()).toEqual(['tpl-no-header', 'tpl-text-header']);
  });

  it('returns no templates and makes no call while no channel is selected', () => {
    const { result } = renderHook(() => useApprovedTemplates(''));
    expect(result.current).toEqual([]);
    expect(listTemplatesMock).not.toHaveBeenCalled();
  });

  it('resolves to an empty list (not a thrown error) when the service call rejects', async () => {
    listTemplatesMock.mockRejectedValueOnce(new Error('network'));
    const { result } = renderHook(() => useApprovedTemplates('chn-1'));
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current).toEqual([]);
  });
});
