'use client';

import { useParams } from 'next/navigation';
import { IdeaPage } from '@/components/platform/idea-portal';

/** One item on a personal feedback link: `id` is the item number the link
 * carries (or the row id when navigating inside the board). */
export default function FeedbackLinkItemPage() {
  const params = useParams();
  return <IdeaPage ideaId={String(params.id)} />;
}
