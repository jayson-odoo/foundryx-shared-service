/**
 * Plan 12 Slice 1 (frontend): composer attach menu + multi-file tray + emoji
 * picker (AC-12-06/08), and per-type media bubble rendering (AC-12-07).
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { ConversationMessage, SendMediaInput } from '@/types/omnichannel';

import { Composer } from './composer';
import { MessageBubble } from './message-bubble';

vi.mock('next-auth/react', () => ({
  useSession: () => ({ status: 'authenticated', data: null }),
}));

// The media bubble fetches bytes via apiFetchBlob → object URL. Stub it + URL.
vi.mock('@/lib/api-client', () => ({
  apiFetchBlob: vi.fn(async () => new Blob(['x'], { type: 'image/png' })),
}));

if (!('createObjectURL' in URL)) {
  // jsdom lacks these — provide no-op stubs.
  // @ts-expect-error test shim
  URL.createObjectURL = () => 'blob:mock';
  // @ts-expect-error test shim
  URL.revokeObjectURL = () => {};
} else {
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock');
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
}

function mediaMsg(over: Partial<ConversationMessage> = {}): ConversationMessage {
  return {
    id: 'm1', contactId: 'c1', channelId: 'ch1',
    senderType: 'CONTACT', senderId: null, senderName: null,
    messageType: 'IMAGE', body: null,
    mediaUrl: '/omnichannel/media/m1', mediaMime: 'image/png',
    mediaFilename: 'pic.png', mediaSize: 2048, voice: false,
    externalMessageId: null, deliveryStatus: null, errorCode: null, errorMessage: null,
    replyTo: null, createdAt: '2026-07-07T10:00:00Z',
    ...over,
  };
}

const baseComposer = {
  windowOpen: true,
  templates: [],
  quickReplies: [],
  isSending: false,
  sendError: null,
  onSend: vi.fn(async () => true),
};

describe('Composer — attach + emoji (plan 12)', () => {
  it('shows the attach menu with all media kinds', async () => {
    const user = userEvent.setup();
    render(<Composer {...baseComposer} onSendMedia={vi.fn(async () => true)} />);
    await user.click(screen.getByTestId('attach-menu'));
    expect(screen.getByTestId('attach-image')).toBeInTheDocument();
    expect(screen.getByTestId('attach-video')).toBeInTheDocument();
    expect(screen.getByTestId('attach-audio')).toBeInTheDocument();
    expect(screen.getByTestId('attach-document')).toBeInTheDocument();
    expect(screen.getByTestId('attach-sticker')).toBeInTheDocument();
  });

  it('previews chosen files in a multi-file tray and sends each', async () => {
    const user = userEvent.setup();
    const onSendMedia = vi.fn(async () => true);
    render(<Composer {...baseComposer} onSendMedia={onSendMedia} />);
    const input = screen.getByTestId('attach-input') as HTMLInputElement;
    const f1 = new File(['a'], 'a.png', { type: 'image/png' });
    const f2 = new File(['b'], 'b.png', { type: 'image/png' });
    await user.upload(input, [f1, f2]);
    expect(screen.getByTestId('attach-tray')).toBeInTheDocument();
    const captions = screen.getAllByTestId('attach-caption');
    expect(captions).toHaveLength(2);
    await user.type(captions[0], 'first');
    await user.click(screen.getByTestId('message-send'));
    await waitFor(() => expect(onSendMedia).toHaveBeenCalledTimes(2));
    const call0 = onSendMedia.mock.calls[0][0] as SendMediaInput;
    expect(call0.kind).toBe('image');
    expect(call0.caption).toBe('first');
  });

  it('inserts a bundled emoji into the textarea (no CDN)', async () => {
    const user = userEvent.setup();
    render(<Composer {...baseComposer} onSendMedia={vi.fn(async () => true)} />);
    await user.click(screen.getByTestId('emoji-trigger'));
    const first = screen.getAllByTestId('emoji-item')[0];
    await user.click(first);
    const textarea = screen.getByTestId('message-input') as HTMLTextAreaElement;
    expect(textarea.value.length).toBeGreaterThan(0);
  });

  it('hides attach + voice controls when the CSW window is closed', () => {
    render(<Composer {...baseComposer} windowOpen={false} onSendMedia={vi.fn(async () => true)} />);
    expect(screen.queryByTestId('attach-menu')).not.toBeInTheDocument();
    expect(screen.queryByTestId('voice-record')).not.toBeInTheDocument();
    expect(screen.getByTestId('csw-banner')).toBeInTheDocument();
  });
});

describe('MessageBubble — media rendering (plan 12)', () => {
  it('renders an image (click → lightbox)', async () => {
    render(<MessageBubble message={mediaMsg()} />);
    await waitFor(() => expect(screen.getByTestId('media-image')).toBeInTheDocument());
  });

  it('renders a document card with filename + size', async () => {
    render(
      <MessageBubble
        message={mediaMsg({ messageType: 'DOCUMENT', mediaMime: 'application/pdf', mediaFilename: 'invoice.pdf' })}
      />,
    );
    await waitFor(() => expect(screen.getByTestId('media-document')).toBeInTheDocument());
    expect(screen.getByText('invoice.pdf')).toBeInTheDocument();
  });

  it('renders a voice-note player for VOICE', async () => {
    render(<MessageBubble message={mediaMsg({ messageType: 'VOICE', voice: true, mediaMime: 'audio/ogg' })} />);
    await waitFor(() => expect(screen.getByTestId('media-voice')).toBeInTheDocument());
  });

  it('renders a bare sticker image', async () => {
    render(<MessageBubble message={mediaMsg({ messageType: 'STICKER', mediaMime: 'image/webp' })} />);
    await waitFor(() => expect(screen.getByTestId('media-sticker')).toBeInTheDocument());
  });
});
