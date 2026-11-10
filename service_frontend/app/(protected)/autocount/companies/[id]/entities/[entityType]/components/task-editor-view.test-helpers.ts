import { afterEach, beforeEach, vi } from 'vitest';

/**
 * Nit (sprint-5/08 review round 2) - every `task-editor-view.*.test.tsx`
 * file that renders the REAL `TaskEditorView` tree (only the data hooks
 * are mocked, never `next-auth/react` itself) reaches `lib/api-client.ts`'s
 * `getSession()`/`signOut()` calls for real. Under Vitest's jsdom
 * environment `fetch` is Node's own undici, which validates `signOut()`'s
 * POST body (`new URLSearchParams(...)`, constructed under jsdom's realm)
 * with an `instanceof` check against undici's OWN `URLSearchParams` - a
 * cross-realm mismatch that throws `TypeError: Request constructor:
 * Expected init.body ("URLSearchParams {}") to be an instance of
 * URLSearchParams` as an UNHANDLED rejection once the real network call
 * actually lands, well after the test that triggered it has finished.
 *
 * ONE shared stub, called at the top of each affected file, keeps every
 * next-auth network call from ever reaching real `fetch` - none of these
 * tests assert on raw fetch traffic, so a blanket 200 is safe.
 */
export function stubAuthFetch(): void {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({}), { status: 200 })),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });
}
