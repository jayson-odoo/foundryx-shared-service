'use client';

import { useParams } from 'next/navigation';
import { EmbedIdeaDetail } from '../embed-idea-detail';

/**
 * Chrome-less embed idea detail (PLAN-ideation-embed-sso §9, AC-E-8/11). Reached
 * by clicking a card in the embed board — navigation stays inside the iframe and
 * carries the fragment token, so no second session is minted.
 */
export default function EmbedIdeaDetailPage() {
  const params = useParams();
  const id = String(params.id);
  return <EmbedIdeaDetail ideaId={id} />;
}
