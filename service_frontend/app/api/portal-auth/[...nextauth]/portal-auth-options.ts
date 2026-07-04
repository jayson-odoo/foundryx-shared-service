import { NextAuthOptions, Session, User } from 'next-auth';
import { JWT } from 'next-auth/jwt';
import CredentialsProvider from 'next-auth/providers/credentials';
import { deriveTenantSlug } from '@/lib/tenant';

/**
 * Profile Portal NextAuth instance (Cluster E, slice 0a — AC-06-18).
 *
 * This is a SECOND, fully-independent NextAuth handler whose session is the
 * external **Profile** identity, NOT the staff user. The crux of AC-06-18 is
 * cookie isolation: the portal session token uses a DISTINCT cookie name from
 * the staff `next-auth.session-token`, so signing into the portal never
 * authenticates the staff `(protected)` app and vice-versa. The portal
 * SessionProvider mounts with `basePath="/api/portal-auth"` to talk to this
 * handler instead of the staff one.
 *
 * FastAPI owns Profile auth end-to-end (POST /portal/auth/login | login-otp);
 * NextAuth only carries the issued Profile JWT client-side.
 */
const API_URL = process.env.BACKEND_API_URL ?? 'http://localhost:8000';

// BL-005 mirror: a backend outage must read differently from bad credentials.
const SERVICE_UNAVAILABLE_MESSAGE =
  'Service temporarily unavailable — please try again.';

/** A Profile's persona membership scoped to a project/context (slice 0b). */
export interface PortalPersona {
  personaId: string;
  personaKey: string;
  scopeType: string | null;
  scopeId: string | null;
}

/** The Profile identity carried in the portal session (subset of /portal/auth/me). */
export interface PortalProfile {
  id: string;
  tenantId: string;
  email: string;
  fullName: string | null;
  portalPerms: string[];
  personas: PortalPersona[];
}

/** Backend session payload from /portal/auth/login | login-otp. */
interface PortalLoginResponse {
  access_token: string;
  token_type?: string;
  profile?: {
    id?: string | number;
    tenantId?: string;
    email?: string;
    fullName?: string | null;
    portalPerms?: string[];
    personas?: PortalPersona[];
  };
}

function errorEnvelope(code: number, message: string): Error {
  return new Error(JSON.stringify({ code, message }));
}

// Build the credentials provider, then pin its id so signIn('portal-credentials')
// targets it unambiguously (the CredentialsProvider config `id` is not always
// honored across next-auth versions — override the resolved value).
const portalCredentialsProvider = CredentialsProvider({
  // ONE provider branches password vs OTP on whether `code` is supplied —
  // both hit FastAPI and yield the SAME session shape.
  id: 'portal-credentials',
  name: 'Portal',
  credentials: {
    email: { label: 'Email', type: 'text' },
    password: { label: 'Password', type: 'password' },
    // Email verification code (OTP) — present ⇒ the OTP login path.
    code: { label: 'Code', type: 'text' },
    rememberMe: { label: 'Remember me', type: 'boolean' },
  },
  async authorize(credentials, req) {
    const email = credentials?.email;
    const code = credentials?.code;
    const password = credentials?.password;
    const isOtp = Boolean(code);

    if (!email || (!password && !code)) {
      throw errorEnvelope(400, 'Please enter your email and credentials.');
    }

    // Tenant resolution mirrors staff login: the host names the tenant.
    const host = (req?.headers?.host as string | undefined) ?? '';
    const tenantSlug = deriveTenantSlug(host);
    const rememberMe = credentials?.rememberMe === 'true';

    const endpoint = isOtp
      ? `${API_URL}/portal/auth/login-otp`
      : `${API_URL}/portal/auth/login`;
    const body = isOtp
      ? { email, code, tenantSlug, rememberMe }
      : { email, password, tenantSlug, rememberMe };

    let res: Response;
    try {
      res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
    } catch {
      throw errorEnvelope(503, SERVICE_UNAVAILABLE_MESSAGE);
    }

    if (!res.ok) {
      if (res.status >= 500) {
        throw errorEnvelope(res.status, SERVICE_UNAVAILABLE_MESSAGE);
      }
      let message = isOtp
        ? 'Invalid or expired code.'
        : 'Invalid email or password.';
      try {
        const data = await res.json();
        message = data.detail ?? data.message ?? message;
      } catch {
        // non-JSON error body — keep the generic message
      }
      throw errorEnvelope(res.status, message);
    }

    const data = (await res.json()) as PortalLoginResponse;
    const p = data.profile ?? {};

    // NextAuth's User type is the staff augmentation; the portal stores its own
    // claims under it and reads them back in the callbacks. Cast at this single
    // boundary (explicit PortalProfile shape via `portal`).
    return {
      id: String(p.id ?? ''),
      email: p.email ?? String(email),
      name: p.fullName ?? 'Profile',
      accessToken: data.access_token,
      portal: {
        id: String(p.id ?? ''),
        tenantId: p.tenantId ?? '',
        email: p.email ?? String(email),
        fullName: p.fullName ?? null,
        portalPerms: Array.isArray(p.portalPerms) ? p.portalPerms : [],
        personas: Array.isArray(p.personas) ? p.personas : [],
      },
    } as unknown as User;
  },
});
portalCredentialsProvider.id = 'portal-credentials';

const isProd = process.env.NODE_ENV === 'production';

const portalAuthOptions: NextAuthOptions = {
  providers: [portalCredentialsProvider],
  session: {
    strategy: 'jwt',
    maxAge: 30 * 24 * 60 * 60,
  },
  // COOKIE ISOLATION — the heart of AC-06-18. Distinct cookie names (+ matching
  // csrf/callback names) mean the portal session NEVER collides with the staff
  // `next-auth.session-token`; the two sessions are fully independent.
  cookies: {
    sessionToken: {
      name: isProd ? '__Secure-portal.session-token' : 'portal.session-token',
      options: {
        httpOnly: true,
        sameSite: 'lax',
        path: '/',
        secure: isProd,
      },
    },
    callbackUrl: {
      name: isProd ? '__Secure-portal.callback-url' : 'portal.callback-url',
      options: {
        sameSite: 'lax',
        path: '/',
        secure: isProd,
      },
    },
    csrfToken: {
      name: isProd ? '__Host-portal.csrf-token' : 'portal.csrf-token',
      options: {
        httpOnly: true,
        sameSite: 'lax',
        path: '/',
        secure: isProd,
      },
    },
  },
  callbacks: {
    async jwt({ token, user }: { token: JWT; user?: User }) {
      if (user) {
        const portal = (user as unknown as { portal?: PortalProfile }).portal;
        token.accessToken = (user as User).accessToken;
        if (portal) {
          (token as unknown as { portal?: PortalProfile }).portal = portal;
        }
      }
      return token;
    },
    async session({ session, token }: { session: Session; token: JWT }) {
      const portal = (token as unknown as { portal?: PortalProfile }).portal;
      const target = session as unknown as {
        accessToken?: string;
        profile?: PortalProfile;
      };
      target.accessToken = token.accessToken;
      if (portal) target.profile = portal;
      return session;
    },
  },
  pages: {
    signIn: '/portal/login',
  },
};

export default portalAuthOptions;
