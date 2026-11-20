import type { Metadata } from 'next';

/**
 * Issue #90 W1 (AC-90-1xx security note, plan s1.7 point 4) - idea content is
 * now visible to anyone holding the link. Mitigations that live at this
 * layer: never indexed, never referred onward from this page (a link the
 * page itself contains would otherwise leak the token in the Referer header).
 * `Cache-Control: no-store` on the 200 is the backend's job (router).
 */
export const metadata: Metadata = {
  robots: { index: false, follow: false },
  referrer: 'no-referrer',
};

export default function PublicIdeaLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
