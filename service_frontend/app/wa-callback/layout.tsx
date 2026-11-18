import type { ReactNode } from 'react';
import { FxComponentsOff } from '@/components/fx/fx-components-off';

/** Signed-out callback page: global look only, no fx components. */
export default function WaCallbackLayout({ children }: { children: ReactNode }) {
  return <FxComponentsOff>{children}</FxComponentsOff>;
}
