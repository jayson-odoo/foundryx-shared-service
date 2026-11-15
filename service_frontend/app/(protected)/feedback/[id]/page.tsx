'use client';

import { useParams, useSearchParams } from 'next/navigation';
import { IdeaFormView } from '../components/idea-form-view';

// TODO(Phase 2): wrap in <RequirePermission permission="ideas.view"> once the
// ideation module + permissions are seeded backend-side.
export default function IdeaFormPage() {
  const params = useParams();
  const id = String(params.id);
  const initialEditing = useSearchParams().get('edit') === '1';
  return <IdeaFormView ideaId={id} initialEditing={initialEditing} />;
}
