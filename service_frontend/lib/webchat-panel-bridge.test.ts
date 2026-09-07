import { afterEach, describe, expect, it, vi } from 'vitest';
import type { WebchatSessionResult } from '@/types/omnichannel';
import {
  isEmbedded,
  postToLoader,
  readLoaderFrame,
  sessionFromPayload,
} from './webchat-panel-bridge';

/**
 * The panel <-> loader bridge (plan 34 / A7b, BL-SS-183). These tests pin the
 * two properties the fix rests on: the panel only ever accepts a frame from
 * its own embedding window, and a session payload is structurally validated
 * before its token is used to authorize anything.
 */

/** Stand in for the embedding loader window. `window.parent === window` in
 *  jsdom, so a test that needs an embed redefines it. */
function embedIn(parent: Window): void {
  Object.defineProperty(window, 'parent', { value: parent, configurable: true });
}

function loaderFrame(overrides: Record<string, unknown> = {}): MessageEvent {
  return {
    source: window.parent,
    data: { source: 'fx-webchat-loader', type: 'open', payload: {}, ...overrides },
  } as unknown as MessageEvent;
}

function validSession(): WebchatSessionResult {
  return {
    token: 'tok-1',
    expiresAt: '2026-10-01T00:00:00Z',
    visitorId: 'vis-1',
    workspaceId: 'ws-1',
    config: {
      appearance: {
        accentColor: '#FF5A00',
        position: 'right',
        headerTitle: 'Chat',
        agentDisplayName: 'Support',
      },
      greeting: 'Hi there!',
      offlineGreeting: 'We are away.',
      preChat: { askName: false, askEmail: false, askPhone: false },
      agentDisplayName: 'Support',
      tenantName: null,
      brandTokens: {},
    },
    online: true,
    messages: [],
  };
}

afterEach(() => {
  Object.defineProperty(window, 'parent', { value: window, configurable: true });
  vi.restoreAllMocks();
});

describe('webchat panel bridge - inbound frames', () => {
  it('accepts a loader frame from the embedding window', () => {
    const parent = { postMessage: vi.fn() } as unknown as Window;
    embedIn(parent);
    const frame = readLoaderFrame(loaderFrame({ type: 'open' }));
    expect(frame?.type).toBe('open');
  });

  it('rejects a frame from any window that is not the embedding one', () => {
    const parent = { postMessage: vi.fn() } as unknown as Window;
    embedIn(parent);
    const foreign = {
      source: { postMessage: vi.fn() },
      data: { source: 'fx-webchat-loader', type: 'open' },
    } as unknown as MessageEvent;
    expect(readLoaderFrame(foreign)).toBeNull();
  });

  it('rejects a frame that does not carry the loader discriminant or a known type', () => {
    const parent = { postMessage: vi.fn() } as unknown as Window;
    embedIn(parent);
    expect(readLoaderFrame(loaderFrame({ source: 'someone-else' }))).toBeNull();
    expect(readLoaderFrame(loaderFrame({ type: 'evict' }))).toBeNull();
    expect(readLoaderFrame({ source: window.parent, data: null } as unknown as MessageEvent)).toBeNull();
  });

  it('a panel with no loader (direct navigation) accepts nothing and posts nothing', () => {
    // `window.parent === window` - the default in this file's afterEach.
    expect(isEmbedded()).toBe(false);
    const spy = vi.spyOn(window, 'postMessage');
    postToLoader('ready');
    expect(spy).not.toHaveBeenCalled();
    expect(
      readLoaderFrame({
        source: window,
        data: { source: 'fx-webchat-loader', type: 'session', payload: validSession() },
      } as unknown as MessageEvent),
    ).toBeNull();
  });
});

describe('webchat panel bridge - session payload validation', () => {
  it('accepts a well-formed session', () => {
    expect(sessionFromPayload(validSession())?.token).toBe('tok-1');
  });

  it('rejects a payload with no usable token', () => {
    expect(sessionFromPayload({ ...validSession(), token: '' })).toBeNull();
    expect(sessionFromPayload({ ...validSession(), token: 42 })).toBeNull();
  });

  it('rejects a payload missing the config the panel renders from', () => {
    const withoutConfig: Record<string, unknown> = { ...validSession() };
    delete withoutConfig.config;
    expect(sessionFromPayload(withoutConfig)).toBeNull();
    expect(sessionFromPayload({ ...validSession(), config: { appearance: {} } })).toBeNull();
  });

  it('rejects non-objects and a missing transcript', () => {
    expect(sessionFromPayload(null)).toBeNull();
    expect(sessionFromPayload('tok-1')).toBeNull();
    expect(sessionFromPayload({ ...validSession(), messages: null })).toBeNull();
  });
});
