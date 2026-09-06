'use client';

import { LoaderCircleIcon } from 'lucide-react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { useActiveWorkspace } from '@/hooks/use-contacts';
import { ContactFormView } from '../components/contact-form-view';

export default function NewContactPage() {
  const { workspaceId, ready } = useActiveWorkspace();

  return (
    <RequirePermission permission="contacts.manage">
      {!ready || !workspaceId ? (
        <Container width="fluid">
          <div className="flex items-center justify-center py-24 text-muted-foreground">
            <LoaderCircleIcon className="size-6 animate-spin" />
          </div>
        </Container>
      ) : (
        <ContactFormView workspaceId={workspaceId} />
      )}
    </RequirePermission>
  );
}
