/**
 * Meta WhatsApp Embedded Signup (Route A - Foundryx = Tech Provider).
 *
 * SELF-HOSTED REDIRECT FLOW. We do NOT use `FB.login` (the JS SDK): under Meta's
 * forced "Use Strict Mode for redirect URIs", `FB.login` mints the code against a
 * dynamic internal `xd_arbiter` URL that can never be matched server-side, so the
 * token exchange always fails with error 36008. Instead we drive Meta's OAuth
 * dialog ourselves with a redirect_uri WE own + registered - the code is bound to
 * that fixed URL, and the backend exchanges with the identical value. The WABA +
 * phone number are then read back from the token (no postMessage needed).
 *
 * The dialog opens in a popup; Meta redirects it to `/wa-callback?code=…`, which
 * relays the code to this opener via postMessage. Gated by env: when
 * `NEXT_PUBLIC_META_APP_ID` + `NEXT_PUBLIC_META_ES_CONFIG_ID` are unset (dev / no
 * Meta app) the wizard falls back to the simulated popup instead.
 */
import type { ChannelType, EmbeddedSignupResult } from '@/types/omnichannel';

const META_APP_ID = process.env.NEXT_PUBLIC_META_APP_ID ?? '';
const META_CONFIG_ID = process.env.NEXT_PUBLIC_META_ES_CONFIG_ID ?? '';
const GRAPH_VERSION = process.env.NEXT_PUBLIC_META_GRAPH_VERSION ?? 'v23.0';

/**
 * Messenger and Instagram share the WhatsApp Meta app (D-A7-1) - only the
 * OAuth **config id** is per product, each falling back to the WhatsApp one
 * so a tenant with a single Business Login config keeps working unchanged.
 * `WEBCHAT` (plan 34 / A7b) has no Meta app at all (D-A7B-1) - unreachable in
 * practice (the connect wizard never calls `launchEmbeddedSignup` for it),
 * the empty string is a defensive fallback, not a real config.
 */
const META_PRODUCT_CONFIG_ID: Record<ChannelType, string> = {
  WHATSAPP: META_CONFIG_ID,
  FACEBOOK: process.env.NEXT_PUBLIC_META_MESSENGER_ES_CONFIG_ID || META_CONFIG_ID,
  INSTAGRAM: process.env.NEXT_PUBLIC_META_INSTAGRAM_ES_CONFIG_ID || META_CONFIG_ID,
  WEBCHAT: '',
};

/** Path of our OAuth callback page - must be registered as a Valid OAuth
 *  Redirect URI in the Meta app (Facebook Login for Business → Settings). */
const CALLBACK_PATH = '/wa-callback';

/** Exact origins Meta's Embedded Signup posts its session info from. */
const FB_ORIGINS = new Set([
  'https://www.facebook.com',
  'https://web.facebook.com',
  'https://business.facebook.com',
  'https://m.facebook.com',
]);

/** True only when the Meta app is configured - drives real-vs-simulated popup. */
export function isEmbeddedSignupConfigured(): boolean {
  return Boolean(META_APP_ID && META_CONFIG_ID);
}

/** postMessage envelope the callback page relays back to this window. */
interface OAuthMessage {
  type: 'FX_WA_OAUTH';
  code?: string;
  error?: string;
  /** Echo of the `state` this window sent (login-CSRF check). */
  state?: string | null;
}

/** A fresh random OAuth `state` per dialog. */
function newOAuthState(): string {
  const bytes = new Uint8Array(16);
  window.crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

/** Meta's Embedded Signup session-info message - identifies the EXACT number the
 *  user selected/registered, so we don't have to guess it from the token. */
interface WaSessionInfo {
  phone_number_id?: string;
  waba_id?: string;
}

export interface MetaOAuthOptions {
  appId: string;
  /** Facebook Login for Business configuration id. */
  configId: string;
  graphVersion: string;
  /** Meta's `extras` dialog parameter (Embedded Signup session info). */
  extras?: Record<string, unknown>;
  windowName?: string;
  /** Messages Meta posts to the opener while the dialog runs (exact-origin
   *  filtered here first). */
  onProviderMessage?: (data: unknown) => void;
}

export interface MetaOAuthResult {
  code: string;
  redirectUri: string;
}

export interface OAuthPopupOptions {
  windowName?: string;
  /** Messages Meta posts to the opener while the dialog runs (exact-origin
   *  filtered here first). */
  onProviderMessage?: (data: unknown) => void;
}

/**
 * The ONE OAuth popup (WhatsApp Embedded Signup, Messenger/Instagram Business
 * Login, Lead Capture's Facebook AND Google sign-in, plan 68). The provider
 * only builds its dialog URL from OUR registered redirect URI (`/wa-callback`)
 * and a fresh random `state`; the callback page relays the code back to this
 * window, and only a code relayed with THIS dialog's `state` is accepted
 * (login CSRF). Resolves `{code, redirectUri}` (the backend exchanges with the
 * identical redirect URI).
 */
export function launchOAuthPopup(
  dialogUrl: (redirectUri: string, state: string) => string,
  opts: OAuthPopupOptions = {},
): Promise<MetaOAuthResult> {
  if (typeof window === 'undefined') return Promise.reject(new Error('Sign-in runs in the browser only.'));
  const redirectUri = `${window.location.origin}${CALLBACK_PATH}`;
  const state = newOAuthState();
  const popup = window.open(dialogUrl(redirectUri, state), opts.windowName ?? 'fx_oauth', 'popup,width=600,height=760');
  if (!popup) {
    return Promise.reject(new Error('Popup blocked - allow popups for this site and try again.'));
  }

  return new Promise<MetaOAuthResult>((resolve, reject) => {
    let settled = false;
    const cleanup = () => {
      window.removeEventListener('message', onMessage);
      window.removeEventListener('message', onProviderMessage);
      window.clearInterval(timer);
    };
    const settle = (fn: () => void) => {
      if (settled) return;
      settled = true;
      cleanup();
      fn();
    };

    // Exact-origin allowlist - `endsWith('facebook.com')` would also match
    // `evilfacebook.com`.
    const onProviderMessage = (event: MessageEvent) => {
      if (!FB_ORIGINS.has(event.origin) || !opts.onProviderMessage) return;
      try {
        opts.onProviderMessage(typeof event.data === 'string' ? JSON.parse(event.data) : event.data);
      } catch {
        /* non-JSON SDK chatter - ignore */
      }
    };

    // Our callback page relays the auth code back once the provider redirects.
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return;
      const data = event.data as OAuthMessage | undefined;
      if (!data || data.type !== 'FX_WA_OAUTH') return;
      // Only the answer to THIS dialog: a code relayed with another (or no)
      // state is not ours (login CSRF).
      if (data.state !== state) return;
      if (data.code) {
        settle(() => resolve({ code: data.code as string, redirectUri }));
      } else {
        settle(() => reject(new Error(data.error || 'Signup cancelled.')));
      }
    };

    // Popup closed without a message -> the user abandoned the flow.
    const timer = window.setInterval(() => {
      if (popup.closed) settle(() => reject(new Error('Signup cancelled.')));
    }, 500);

    window.addEventListener('message', onMessage);
    window.addEventListener('message', onProviderMessage);
  });
}

/** Meta's OAuth dialog through the ONE popup. */
export function launchMetaOAuth(opts: MetaOAuthOptions): Promise<MetaOAuthResult> {
  const extras = opts.extras ? `&extras=${encodeURIComponent(JSON.stringify(opts.extras))}` : '';
  return launchOAuthPopup(
    (redirectUri, state) =>
      `https://www.facebook.com/${opts.graphVersion}/dialog/oauth` +
      `?client_id=${encodeURIComponent(opts.appId)}` +
      `&config_id=${encodeURIComponent(opts.configId)}` +
      `&response_type=code` +
      `&override_default_response_type=true` +
      `&redirect_uri=${encodeURIComponent(redirectUri)}` +
      `&state=${state}` +
      extras,
    { windowName: opts.windowName ?? 'fx_meta_oauth', onProviderMessage: opts.onProviderMessage },
  );
}

/**
 * Launch Embedded Signup / Business Login. Opens Meta's OAuth dialog in a
 * popup and resolves with the auth code once the tenant finishes. `product`
 * selects the per-product config id (D-A7-1); WABA + phone ids are resolved
 * server-side from the exchanged token for WhatsApp, so they're omitted here.
 */
export async function launchEmbeddedSignup(
  product: ChannelType = 'WHATSAPP',
): Promise<EmbeddedSignupResult> {
  // Captured from Meta's ES FINISH message during the flow - the EXACT number
  // the user picked. Falls back to server-side token resolution if absent.
  let session: WaSessionInfo = {};
  const { code, redirectUri } = await launchMetaOAuth({
    appId: META_APP_ID,
    configId: META_PRODUCT_CONFIG_ID[product],
    graphVersion: GRAPH_VERSION,
    extras: { setup: {}, featureType: '', sessionInfoVersion: '3' },
    windowName: 'fx_wa_es',
    onProviderMessage: (data) => {
      const msg = data as { type?: string; event?: string; data?: WaSessionInfo } | null;
      if (msg?.type === 'WA_EMBEDDED_SIGNUP' && msg.event === 'FINISH') {
        session = msg.data ?? {};
      }
    },
  });
  return {
    code,
    wabaId: session.waba_id ?? '',
    phoneNumberId: session.phone_number_id ?? '',
    redirectUri,
  };
}
