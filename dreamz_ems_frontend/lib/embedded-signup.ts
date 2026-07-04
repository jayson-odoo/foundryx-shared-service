/**
 * Meta WhatsApp Embedded Signup (Route A — Dreamz = Tech Provider).
 *
 * Loads Meta's JS SDK and launches the Embedded Signup popup. The tenant logs
 * into Facebook, picks/registers their WhatsApp number, and Meta hands back an
 * auth `code` (via FB.login) plus `waba_id` + `phone_number_id` (via a window
 * message event). We post those to the backend `oauth-callback`, which exchanges
 * the code for a permanent token against the ONE Dreamz Meta app.
 *
 * Gated by env: when `NEXT_PUBLIC_META_APP_ID` + `NEXT_PUBLIC_META_ES_CONFIG_ID`
 * are unset (dev / no Meta app yet) the wizard falls back to the simulated popup,
 * so local dev + tests don't need a real Meta app.
 */
import type { EmbeddedSignupResult } from '@/types/omnichannel';

const META_APP_ID = process.env.NEXT_PUBLIC_META_APP_ID ?? '';
const META_CONFIG_ID = process.env.NEXT_PUBLIC_META_ES_CONFIG_ID ?? '';
const GRAPH_VERSION = process.env.NEXT_PUBLIC_META_GRAPH_VERSION ?? 'v19.0';

/** True only when the Meta app is configured — drives real-vs-simulated popup. */
export function isEmbeddedSignupConfigured(): boolean {
  return Boolean(META_APP_ID && META_CONFIG_ID);
}

/* eslint-disable @typescript-eslint/no-explicit-any */
declare global {
  interface Window {
    FB?: any;
    fbAsyncInit?: () => void;
  }
}

let sdkPromise: Promise<void> | null = null;

function loadSdk(): Promise<void> {
  if (typeof window === 'undefined') return Promise.reject(new Error('SSR'));
  if (window.FB) return Promise.resolve();
  if (sdkPromise) return sdkPromise;

  sdkPromise = new Promise<void>((resolve, reject) => {
    window.fbAsyncInit = () => {
      window.FB.init({ appId: META_APP_ID, autoLogAppEvents: true, xfbml: false, version: GRAPH_VERSION });
      resolve();
    };
    const script = document.createElement('script');
    script.src = 'https://connect.facebook.net/en_US/sdk.js';
    script.async = true;
    script.defer = true;
    script.crossOrigin = 'anonymous';
    script.onerror = () => reject(new Error('Failed to load the Facebook SDK.'));
    document.body.appendChild(script);
  });
  return sdkPromise;
}

/**
 * Launch Embedded Signup. Resolves with the auth code + WABA/phone ids once the
 * tenant finishes. Display number/name are resolved server-side from the
 * phone_number_id, so they're omitted here.
 */
export async function launchEmbeddedSignup(): Promise<EmbeddedSignupResult> {
  await loadSdk();

  return new Promise<EmbeddedSignupResult>((resolve, reject) => {
    let sessionInfo: { phone_number_id?: string; waba_id?: string } | null = null;
    let aborted: string | null = null;

    const onMessage = (event: MessageEvent) => {
      if (typeof event.origin !== 'string' || !event.origin.endsWith('facebook.com')) return;
      try {
        const msg = JSON.parse(event.data);
        if (msg?.type !== 'WA_EMBEDDED_SIGNUP') return;
        if (msg.event === 'FINISH') sessionInfo = msg.data ?? msg;
        else if (msg.event === 'CANCEL') aborted = 'Signup cancelled.';
        else if (msg.event === 'ERROR') aborted = msg.data?.error_message || 'Signup failed.';
      } catch {
        /* non-JSON messages from the SDK — ignore */
      }
    };
    window.addEventListener('message', onMessage);
    const cleanup = () => window.removeEventListener('message', onMessage);

    window.FB.login(
      (response: any) => {
        cleanup();
        if (aborted) {
          reject(new Error(aborted));
          return;
        }
        const code = response?.authResponse?.code;
        if (!code) {
          reject(new Error('Signup cancelled.'));
          return;
        }
        resolve({
          code,
          wabaId: sessionInfo?.waba_id ?? '',
          phoneNumberId: sessionInfo?.phone_number_id ?? '',
          // Resolved server-side from phone_number_id.
          displayPhoneNumber: '',
          businessName: '',
        });
      },
      {
        config_id: META_CONFIG_ID,
        response_type: 'code',
        override_default_response_type: true,
        extras: { setup: {}, featureType: '', sessionInfoVersion: '3' },
      },
    );
  });
}
