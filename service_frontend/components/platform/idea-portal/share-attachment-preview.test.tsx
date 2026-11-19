import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AttachmentThumbs } from '@/components/platform/attachment-preview/attachment-thumbs';
import { IdeaPortalContext, PORTAL_PATHS, usePortalAttachmentFetch, type IdeaPortalRuntime } from '@/hooks/use-idea-portal';
import { ideaPortalAuth } from '@/lib/idea-portal-auth';
import type { IdeaAttachment } from '@/types/ideation';

/** Lane FEEDBACK-IMAGE-PREVIEW: on the public share page an image attachment
 * opens as a picture (not "Preview unavailable."). The file comes from the
 * token-checked share route: no portal token is sent, and a refusal never
 * clears a portal session the visitor holds. Runs the real hook + service over
 * a mocked `fetch`. */

const SHARE_PATH = '/portal/ideas/shared/tok/i1/attachments/a1/content';
const PORTAL_PATH = '/portal/ideas/i1/attachments/a1/content';

function file(contentPath: string): IdeaAttachment {
  return { id: 'a1', kind: 'image', name: 'image.png', url: '', sizeBytes: 10, contentPath } as IdeaAttachment;
}

function runtime(mode: IdeaPortalRuntime['mode']): IdeaPortalRuntime {
  return {
    mode,
    shareToken: mode === 'share' ? 'tok' : undefined,
    paths: PORTAL_PATHS,
    principal: { kind: mode === 'share' ? 'share' : 'contact', name: null, role: 'Visitor', productId: null, canManage: false },
    signOut: () => undefined,
  } as IdeaPortalRuntime;
}

function Thumbs({ path }: { path: string }) {
  const fetchContent = usePortalAttachmentFetch();
  return <AttachmentThumbs attachments={[file(path)]} fetchContent={fetchContent} />;
}

function renderIn(mode: IdeaPortalRuntime['mode'], path: string, children?: ReactNode) {
  return render(
    <IdeaPortalContext.Provider value={runtime(mode)}>
      {children ?? <Thumbs path={path} />}
    </IdeaPortalContext.Provider>,
  );
}

const fetchMock = vi.fn();

/** A 200 whose body is a jsdom Blob (a real `Response` would hand back a
 * Node Blob, which jsdom's Blob constructor cannot wrap). */
function served(): Response {
  return { ok: true, status: 200, blob: async () => new Blob(['png'], { type: 'image/png' }) } as unknown as Response;
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
  URL.createObjectURL = vi.fn(() => 'blob:preview');
  URL.revokeObjectURL = vi.fn();
  ideaPortalAuth.set('portal-token');
});
afterEach(() => {
  vi.unstubAllGlobals();
  ideaPortalAuth.set(null);
});

function headersOf(call: unknown[]): Headers {
  return new Headers((call[1] as RequestInit | undefined)?.headers);
}

describe('share page attachment preview', () => {
  it('opens an image in the lightbox as a picture, fetched without the portal token', async () => {
    fetchMock.mockImplementation(async () => served());
    renderIn('share', SHARE_PATH);
    await userEvent.click(screen.getByRole('button', { name: 'image.png' }));
    const dialog = await screen.findByRole('dialog');
    const img = await within(dialog).findByRole('img', { name: 'image.png' });
    expect(img).toHaveAttribute('src', 'blob:preview');
    expect(within(dialog).queryByText('Preview unavailable.')).not.toBeInTheDocument();
    const urls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(urls.some((u) => u.endsWith(SHARE_PATH))).toBe(true);
    expect(urls.some((u) => u.endsWith(`${SHARE_PATH}?variant=thumb`))).toBe(true);
    for (const call of fetchMock.mock.calls) expect(headersOf(call).get('Authorization')).toBeNull();
  });

  it('a refused file on the share page never clears the portal session', async () => {
    fetchMock.mockImplementation(
      async () => new Response(JSON.stringify({ error: { code: 'unauthorized', message: 'x' } }), { status: 401 }),
    );
    renderIn('share', SHARE_PATH);
    await userEvent.click(screen.getByRole('button', { name: 'image.png' }));
    const dialog = await screen.findByRole('dialog');
    await within(dialog).findByText('Preview unavailable.');
    expect(ideaPortalAuth.get()).toBe('portal-token');
  });

  it('the signed-in board still sends the portal token', async () => {
    fetchMock.mockImplementation(async () => served());
    renderIn('link', PORTAL_PATH);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(headersOf(fetchMock.mock.calls[0]).get('Authorization')).toBe('Bearer portal-token');
  });
});
