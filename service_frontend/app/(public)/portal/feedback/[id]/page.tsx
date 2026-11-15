'use client';

import { useParams } from 'next/navigation';
import { IdeaPage } from '@/components/platform/idea-portal';

export default function IdeaPortalIdeaPage() {
  const params = useParams();
  return <IdeaPage ideaId={String(params.id)} />;
}
