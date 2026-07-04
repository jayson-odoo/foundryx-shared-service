import 'next-auth';
import 'next-auth/jwt';

type SessionRole = { id: string; name: string };

declare module 'next-auth' {
  interface Session {
    accessToken?: string;
    user: {
      id: string;
      tenantId: string;
      /** Platform-tenant member — gates the Platform Console menu (UX only). */
      isPlatformTenant: boolean;
      name: string;
      email: string;
      avatar?: string | null;
      roles: SessionRole[];
      permissions: string[];
      status: string;
      /** IANA timezone preference; null = render in the browser tz (plan sprint-2/05). */
      timezone?: string | null;
    };
  }

  interface User {
    id: string;
    tenantId: string;
    isPlatformTenant: boolean;
    name: string;
    email: string;
    avatar?: string | null;
    roles: SessionRole[];
    permissions: string[];
    status: string;
    timezone?: string | null;
    accessToken?: string;
  }
}

declare module 'next-auth/jwt' {
  interface JWT {
    id: string;
    tenantId: string;
    isPlatformTenant: boolean;
    name: string;
    email: string;
    avatar?: string | null;
    roles: SessionRole[];
    permissions: string[];
    status: string;
    timezone?: string | null;
    accessToken?: string;
  }
}
