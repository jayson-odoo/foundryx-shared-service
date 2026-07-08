import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const svc = { get: vi.fn(), update: vi.fn() };
vi.mock('@/services/omnichannel-settings-service', () => ({
  get omnichannelSettingsService() {
    return svc;
  },
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { MediaCapsForm } from './media-caps-form';

const MB = 1024 * 1024;

function settings(overrides: Partial<Record<string, number | null>> = {}) {
  const base = {
    imageMaxBytes: null,
    videoMaxBytes: null,
    audioMaxBytes: null,
    documentMaxBytes: null,
    stickerMaxBytes: null,
    ...overrides,
  };
  const eff = (ceiling: number, mimes: string[], cap: number | null) => ({
    maxBytes: cap === null ? ceiling : Math.min(cap, ceiling),
    ceilingBytes: ceiling,
    acceptedMimes: mimes,
  });
  return {
    workspaceId: null,
    overrides: base,
    effective: {
      IMAGE: eff(5 * MB, ['image/jpeg', 'image/png'], base.imageMaxBytes),
      VIDEO: eff(16 * MB, ['video/mp4'], base.videoMaxBytes),
      AUDIO: eff(16 * MB, ['audio/ogg'], base.audioMaxBytes),
      VOICE: eff(16 * MB, ['audio/ogg'], base.audioMaxBytes),
      DOCUMENT: eff(100 * MB, ['application/pdf'], base.documentMaxBytes),
      STICKER: eff(500 * 1024, ['image/webp'], base.stickerMaxBytes),
    },
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  svc.get.mockResolvedValue(settings());
});

describe('MediaCapsForm', () => {
  it('renders a card per editable cap with ceiling + accepted mimes read-only', async () => {
    render(<MediaCapsForm />);
    await waitFor(() => expect(screen.getByText('Image')).toBeInTheDocument());
    expect(screen.getByText('Audio & voice notes')).toBeInTheDocument();
    expect(screen.getByText('Sticker')).toBeInTheDocument();
    // accepted mimes shown read-only
    expect(screen.getByText('image/png')).toBeInTheDocument();
    expect(screen.getByText('image/webp')).toBeInTheDocument();
    // ceiling hint
    expect(screen.getAllByText(/max .* MB/).length).toBeGreaterThan(0);
  });

  it('prefills an existing override in MB', async () => {
    svc.get.mockResolvedValue(settings({ imageMaxBytes: 2 * MB }));
    render(<MediaCapsForm />);
    const input = (await screen.findByLabelText('Maximum size (MB)', {
      selector: '#cap-imageMaxBytes',
    })) as HTMLInputElement;
    expect(input.value).toBe('2');
  });

  it('clamps an over-ceiling entry and saves bytes; blank clears to null', async () => {
    svc.update.mockResolvedValue(settings());
    render(<MediaCapsForm />);
    await screen.findByText('Sticker');
    // Sticker ceiling is 500KB; typing 5 (MB) must clamp to the ceiling in bytes.
    const sticker = document.querySelector('#cap-stickerMaxBytes') as HTMLInputElement;
    fireEvent.change(sticker, { target: { value: '5' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(svc.update).toHaveBeenCalled());
    const payload = svc.update.mock.calls[0][0];
    expect(payload.stickerMaxBytes).toBe(500 * 1024); // clamped
    expect(payload.imageMaxBytes).toBeNull(); // blank → cleared
  });

  it('disables Save until an input changes', async () => {
    render(<MediaCapsForm />);
    const save = (await screen.findByRole('button', { name: 'Save' })) as HTMLButtonElement;
    expect(save).toBeDisabled();
    fireEvent.change(document.querySelector('#cap-videoMaxBytes') as HTMLInputElement, {
      target: { value: '8' },
    });
    expect(save).not.toBeDisabled();
  });
});
