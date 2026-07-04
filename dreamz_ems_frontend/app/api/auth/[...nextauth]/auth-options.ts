import { NextAuthOptions, Session, User } from 'next-auth';
import { JWT } from 'next-auth/jwt';
import CredentialsProvider from 'next-auth/providers/credentials';
import { deriveTenantSlug } from '@/lib/tenant';

// FastAPI owns auth. NextAuth only validates via the backend and holds the
// session JWT client-side. No Prisma, no local user DB.
const API_URL = process.env.BACKEND_API_URL ?? 'http://localhost:8000';

// BL-005 (plan sprint-2/04): infra failures must read differently from bad
// credentials — a backend outage is not "Invalid email or password."
const SERVICE_UNAVAILABLE_MESSAGE =
  'Service temporarily unavailable — please try again.';

const authOptions: NextAuthOptions = {
  providers: [
    CredentialsProvider({
      name: 'Credentials',
      credentials: {
        email: { label: 'Email', type: 'text' },
        password: { label: 'Password', type: 'password' },
        rememberMe: { label: 'Remember me', type: 'boolean' },
      },
      async authorize(credentials, req) {
        if (!credentials?.email || !credentials?.password) {
          throw new Error(
            JSON.stringify({
              code: 400,
              message: 'Please enter both email and password.',
            }),
          );
        }

        // Tenant resolution by subdomain (plan 07 §6): the host the user signed
        // in on names the tenant (acme.dreamzems.com / platform.localhost).
        const host = (req?.headers?.host as string | undefined) ?? '';
        const tenantSlug = deriveTenantSlug(host);

        let res: Response;
        try {
          res = await fetch(`${API_URL}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              email: credentials.email,
              password: credentials.password,
              tenantSlug,
              // NextAuth serializes credentials to strings — coerce back. The
              // backend JWT exp is the real session boundary (plan 10 D4).
              rememberMe: credentials.rememberMe === 'true',
            }),
          });
        } catch {
          // Backend unreachable (down, DNS, refused) — BL-005: this is an
          // infra failure, NOT a credentials failure.
          throw new Error(
            JSON.stringify({ code: 503, message: SERVICE_UNAVAILABLE_MESSAGE }),
          );
        }

        if (!res.ok) {
          // 5xx = the backend broke, not the user (BL-005). 4xx keeps the
          // backend detail: 401 stays the uniform credentials message (no
          // enumeration regression), 403/429 carry their specific copy.
          if (res.status >= 500) {
            throw new Error(
              JSON.stringify({
                code: res.status,
                message: SERVICE_UNAVAILABLE_MESSAGE,
              }),
            );
          }
          let message = 'Invalid credentials.';
          try {
            const data = await res.json();
            message = data.detail ?? data.message ?? message;
          } catch {
            // backend returned non-JSON (proxy HTML) — keep the generic message
          }
          throw new Error(JSON.stringify({ code: res.status, message }));
        }

        // Backend contract: { access_token, user: {...} }
        const data = await res.json();
        const u = data.user ?? {};

        return {
          id: String(u.id),
          tenantId: u.tenantId ?? '',
          isPlatformTenant: u.isPlatformTenant === true,
          email: u.email,
          name: u.name ?? 'Anonymous',
          avatar: u.avatar ?? null,
          roles: Array.isArray(u.roles) ? u.roles : [],
          permissions: Array.isArray(u.permissions) ? u.permissions : [],
          status: u.status ?? 'ACTIVE',
          timezone: u.timezone ?? null,
          accessToken: data.access_token,
        } as User;
      },
    }),
  ],
  session: {
    strategy: 'jwt',
    // Long enough for "remember me" (30d). The backend JWT carries the real
    // short/long expiry (24h vs 30d, plan 10 D4) — an expired backend token
    // 401s and the api-client treats that as session end either way.
    maxAge: 30 * 24 * 60 * 60,
  },
  callbacks: {
    async jwt({
      token,
      user,
      trigger,
    }: {
      token: JWT;
      user?: User;
      trigger?: 'signIn' | 'signUp' | 'update';
    }) {
      if (user) {
        token.id = user.id;
        token.tenantId = user.tenantId;
        token.isPlatformTenant = user.isPlatformTenant;
        token.email = user.email;
        token.name = user.name;
        token.avatar = user.avatar;
        token.roles = user.roles;
        token.permissions = user.permissions;
        token.status = user.status;
        token.timezone = user.timezone ?? null;
        token.accessToken = user.accessToken;
      }
      // Client `update()` (e.g. after an App-Store action, plan 08 D7): re-pull
      // the effective roles/permissions so the session reflects fresh grants
      // without a re-login. Backend stays the real boundary either way.
      if (trigger === 'update' && token.accessToken) {
        try {
          const res = await fetch(`${API_URL}/auth/me`, {
            headers: { Authorization: `Bearer ${token.accessToken}` },
          });
          if (res.ok) {
            const u = await res.json();
            token.roles = Array.isArray(u.roles) ? u.roles : token.roles;
            token.permissions = Array.isArray(u.permissions)
              ? u.permissions
              : token.permissions;
            token.status = u.status ?? token.status;
            // Identity fields too — the change-email ceremony (plan 04)
            // flips the backend email; update() is how a live session
            // catches up without a re-login.
            token.email = u.email ?? token.email;
            token.name = u.name ?? token.name;
            // `??` would keep a stale avatar forever — null is a meaningful
            // value here ("avatar removed", plan 06 D5), only undefined
            // (field absent) falls back.
            token.avatar = u.avatar === undefined ? token.avatar : u.avatar;
            // Timezone preference (plan sprint-2/05) — null is meaningful
            // (= browser tz), so assign verbatim, no ?? fallback.
            token.timezone = u.timezone ?? null;
          }
        } catch {
          // Network blip — keep the existing claims; next update retries.
        }
      }
      return token;
    },
    async session({ session, token }: { session: Session; token: JWT }) {
      if (session.user) {
        session.user.id = token.id;
        session.user.tenantId = token.tenantId;
        session.user.isPlatformTenant = token.isPlatformTenant ?? false;
        session.user.email = token.email;
        session.user.name = token.name;
        session.user.avatar = token.avatar;
        session.user.roles = token.roles ?? [];
        session.user.permissions = token.permissions ?? [];
        session.user.status = token.status;
        session.user.timezone = token.timezone ?? null;
      }
      session.accessToken = token.accessToken;
      return session;
    },
  },
  pages: {
    signIn: '/signin',
  },
};

export default authOptions;
