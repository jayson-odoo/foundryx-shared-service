'use client';

import { useParams } from 'next/navigation';
import { LoaderCircleIcon } from 'lucide-react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { useActiveWorkspace } from '@/hooks/use-contacts';
import { ContactFormView } from '../components/contact-form-view';

export default function ContactFormPage() {
  const params = useParams();
  const id = String(params.id);
  const { workspaceId, ready } = useActiveWorkspace();

  return (
    <RequirePermission permission="contacts.read">
      {!ready || !workspaceId ? (
        <Container width="fluid">
          <div className="flex items-center justify-center py-24 text-muted-foreground">
            <LoaderCircleIcon className="size-6 animate-spin" />
          </div>
        </Container>
      ) : (
        <ContactFormView contactId={id} workspaceId={workspaceId} />
      )}
    </RequirePermission>
  );
}
