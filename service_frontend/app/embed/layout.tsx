import type { ReactNode } from 'react';
import { FxOff } from '@/components/fx/fx-off';

/**
 * Embedded surfaces keep the host app's look: the Foundryx UIUX switch is
 * always off in here (`<FxOff>`, no DOM of its own). See playbook-uiux.md.
 */
export default function EmbedLayout({ children }: { children: ReactNode }) {
  return <FxOff>{children}</FxOff>;
}
