'use client';

import { IdeaFormView } from '../components/idea-form-view';

// TODO(Phase 2): wrap in <RequirePermission permission="ideas.create">.
export default function NewIdeaPage() {
  return <IdeaFormView initialEditing />;
}
