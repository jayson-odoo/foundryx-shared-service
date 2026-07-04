'use client';

import { useParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { EmailDetailView } from '../components/email-detail-view';

export default function EmailLogDetailPage() {
  const params = useParams();
  const id = String(params.id);

  return (
    <RequirePermission permission="emails.read">
      <EmailDetailView emailId={id} />
    </RequirePermission>
  );
}
