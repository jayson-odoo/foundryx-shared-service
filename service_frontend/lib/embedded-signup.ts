/**
 * Meta WhatsApp Embedded Signup (Route A — FoundryX = Tech Provider).
 *
 * SELF-HOSTED REDIRECT FLOW. We do NOT use `FB.login` (the JS SDK): under Meta's
 * forced "Use Strict Mode for redirect URIs", `FB.login` mints the code against a
 * dynamic internal `xd_arbiter` URL that can never be matched server-side, so the
 * token exchange always fails with error 36008. Instead we drive Meta's OAuth
 * dialog ourselves with a redirect_uri WE own + registered — the code is bound to
 * that fixed URL, and the backend exchanges with the identical value. The WABA +
 * phone number are then read back from the token (no postMessage needed).
 *
 * The dialog opens in a popup; Meta redirects it to `/wa-callback?code=…`, which
 * relays the code to this opener via postMessage. Gated by env: when
 * `NEXT_PUBLIC_META_APP_ID` + `NEXT_PUBLIC_META_ES_CONFIG_ID` are unset (dev / no
 * Meta app) the wizard falls back to the simulated popup instead.
 */
import type { EmbeddedSignupResult } from '@/types/omnichannel';

const META_APP_ID = process.env.NEXT_PUBLIC_META_APP_ID ?? '';
const META_CONFIG_ID = process.env.NEXT_PUBLIC_META_ES_CONFIG_ID ?? '';
const GRAPH_VERSION = process.env.NEXT_PUBLIC_META_GRAPH_VERSION ?? 'v23.0';

/** Path of our OAuth callback page — must be registered as a Valid OAuth
 *  Redirect URI in the Meta app (Facebook Login for Business → Settings). */
const CALLBACK_PATH = '/wa-callback';

/** True only when the Meta app is configured — drives real-vs-simulated popup. */
export function isEmbeddedSignupConfigured(): boolean {
  return Boolean(META_APP_ID && META_CONFIG_ID);
}

/** postMessage envelope the callback page relays back to this window. */
interface OAuthMessage {
  type: 'FX_WA_OAUTH';
  code?: string;
  error?: string;
}

/**
 * Launch Embedded Signup. Opens Meta's OAuth dialog in a popup and resolves with
 * the auth code once the tenant finishes. The WABA + phone ids are resolved
 * server-side from the exchanged token, so they're omitted here.
 */
export async function launchEmbeddedSignup(): Promise<EmbeddedSignupResult> {
  if (typeof window === 'undefined') throw new Error('Embedded Signup runs in the browser only.');

  const redirectUri = `${window.location.origin}${CALLBACK_PATH}`;
  const extras = encodeURIComponent(
    JSON.stringify({ setup: {}, featureType: '', sessionInfoVersion: '3' }),
  );
  const dialogUrl =
    `https://www.facebook.com/${GRAPH_VERSION}/dialog/oauth` +
    `?client_id=${encodeURIComponent(META_APP_ID)}` +
    `&config_id=${encodeURIComponent(META_CONFIG_ID)}` +
    `&response_type=code` +
    `&override_default_response_type=true` +
    `&redirect_uri=${encodeURIComponent(redirectUri)}` +
    `&extras=${extras}`;

  const popup = window.open(dialogUrl, 'fx_wa_es', 'popup,width=600,height=760');
  if (!popup) {
    throw new Error('Popup blocked — allow popups for this site and try again.');
  }

  return new Promise<EmbeddedSignupResult>((resolve, reject) => {
    let settled = false;
    const cleanup = () => {
      window.removeEventListener('message', onMessage);
      window.clearInterval(timer);
    };
    const settle = (fn: () => void) => {
      if (settled) return;
      settled = true;
      cleanup();
      fn();
    };

    const onMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return;
      const data = event.data as OAuthMessage | undefined;
      if (!data || data.type !== 'FX_WA_OAUTH') return;
      if (data.code) {
        settle(() =>
          resolve({ code: data.code as string, wabaId: '', phoneNumberId: '', redirectUri }),
        );
      } else {
        settle(() => reject(new Error(data.error || 'Signup cancelled.')));
      }
    };

    // Popup closed without a message → the tenant abandoned the flow.
    const timer = window.setInterval(() => {
      if (popup.closed) settle(() => reject(new Error('Signup cancelled.')));
    }, 500);

    window.addEventListener('message', onMessage);
  });
}
