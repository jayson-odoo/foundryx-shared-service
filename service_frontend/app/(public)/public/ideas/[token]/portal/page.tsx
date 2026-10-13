'use client';

import { useParams } from 'next/navigation';
import { LinkConfirmView } from '@/components/platform/idea-portal';

/** The chatbot link → portal hand-off (Q1 b): confirm the last 4 digits of
 * the WhatsApp number, then open the idea in the signed-in portal. */
export default function IdeaLinkPortalPage() {
  const params = useParams();
  return <LinkConfirmView token={String(params.token)} />;
}
