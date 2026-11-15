import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import { LinkPortalRoot } from '@/components/platform/idea-portal';

/**
 * A dealer's personal feedback link (lane PUBLIC-IDEAS-BOARD): the existing
 * idea portal, no login, the link token in the path. The link is a bearer
 * credential forwarded over WhatsApp: never indexed, never referred onward.
 * `Cache-Control: no-store` on every API response is the backend's job.
 */
export const metadata: Metadata = {
  title: 'Feedback',
  robots: { index: false, follow: false },
  referrer: 'no-referrer',
};

export default async function FeedbackLinkLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  return <LinkPortalRoot linkToken={token}>{children}</LinkPortalRoot>;
}
