'use client';

import { Fragment, useState } from 'react';
import {
  Toolbar,
  ToolbarDescription,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { ResourceList } from '@/components/platform/resource-list';
import { RequirePermission } from '@/components/common/require-permission';
import type { Persona } from '@/types/persona';
import { usePersonasListConfig } from './use-personas-list-config';
import { PersonaDialog } from './persona-dialog';

/**
 * EMS Personas on the Resource shell (AC-06-26) — configure the Profile-portal
 * roles, grant portal-permission keys per persona. Gated by personas.read /
 * personas.manage (+ the `ems` module tag in the menu).
 */
export default function PersonasPage() {
  const [editing, setEditing] = useState<Persona | 'new' | null>(null);
  const [nonce, setNonce] = useState(0);
  const config = usePersonasListConfig(
    () => setEditing('new'),
    (item) => setEditing(item),
  );

  return (
    <RequirePermission permission="personas.read">
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle text="Personas" />
              <ToolbarDescription>
                Portal roles and the access each grants.
              </ToolbarDescription>
            </ToolbarHeading>
          </Toolbar>
        </Container>
        <Container width="fluid">
          <ResourceList key={nonce} config={config} />
        </Container>
        {editing && (
          <PersonaDialog
            item={editing === 'new' ? null : editing}
            onClose={() => setEditing(null)}
            onSaved={() => {
              setEditing(null);
              setNonce((n) => n + 1);
            }}
          />
        )}
      </Fragment>
    </RequirePermission>
  );
}
