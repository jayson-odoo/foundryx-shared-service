'use client';

import { useParams, useSearchParams } from 'next/navigation';
import { RequirePermission } from '@/components/common/require-permission';
import { ChannelFormView } from '../components/channel-form-view';

export default function ChannelFormPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const id = String(params.id);
  const initialEditing = searchParams.get('edit') === '1';

  return (
    <RequirePermission permission="channels.read">
      <ChannelFormView channelId={id} initialEditing={initialEditing} />
    </RequirePermission>
  );
}
