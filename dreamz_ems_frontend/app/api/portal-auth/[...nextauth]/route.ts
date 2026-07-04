import NextAuth from 'next-auth';
import portalAuthOptions from './portal-auth-options';

// Second, independent NextAuth handler for the Profile Portal (AC-06-18).
// Mounted at /api/portal-auth; the portal SessionProvider points its basePath
// here so it never reads the staff /api/auth session.
const handler = NextAuth(portalAuthOptions);

export { handler as GET, handler as POST };
