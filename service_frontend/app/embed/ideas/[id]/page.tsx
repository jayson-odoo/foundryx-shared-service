'use client';

import { useParams, useSearchParams } from 'next/navigation';
import { IdeaFormView } from '@/app/(protected)/ideation/ideas/components/idea-form-view';
import { EmbedIdeationShell } from '../embed-app';

/**
 * Chrome-less embed idea detail (WS-C / AC-CAP-9). Reached by clicking a row in
 * the embed grid — navigation stays inside the iframe and carries the fragment
 * token, so no second session is minted. Renders the SAME {@link IdeaFormView}
 * the operator detail page uses (one component, two modes); writes go through the
 * embed service (`/embed/*`), scoped to the connection's tenant + product.
 */
export default function EmbedIdeaDetailPage() {
  const params = useParams();
  const id = String(params.id);
  const initialEditing = useSearchParams().get('edit') === '1';
  return (
    <EmbedIdeationShell>
      <IdeaFormView ideaId={id} initialEditing={initialEditing} />
    </EmbedIdeationShell>
  );
}
