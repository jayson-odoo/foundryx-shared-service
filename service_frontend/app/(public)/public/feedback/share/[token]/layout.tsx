import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import { ShareItemRoot } from '@/components/platform/idea-portal';

/**
 * One feedback item's read-only share link (lane FEEDBACK-SUBSCRIBE, owner
 * 17 Nov "a general share link"). Anyone can read it; following, commenting or
 * upvoting asks for the visitor's phone first. The token is a capability
 * forwarded over chat: never indexed, never referred onward.
 */
export const metadata: Metadata = {
  title: 'Feedback',
  robots: { index: false, follow: false },
  referrer: 'no-referrer',
};

export default async function FeedbackShareLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  return <ShareItemRoot shareToken={token}>{children}</ShareItemRoot>;
}
