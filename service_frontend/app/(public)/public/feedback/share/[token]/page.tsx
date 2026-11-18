'use client';

import { useParams } from 'next/navigation';
import { IdeaPage } from '@/components/platform/idea-portal';

/** The shared item. The share token identifies the item, so the id passed to
 * the page is only a placeholder until it loads. */
export default function FeedbackSharePage() {
  const params = useParams();
  return <IdeaPage ideaId={String(params.token)} />;
}
