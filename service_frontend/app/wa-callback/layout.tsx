import type { ReactNode } from 'react';
import type { Metadata } from 'next';
import { FxComponentsOff } from '@/components/fx/fx-components-off';

/** Never send the callback URL (it can carry a code and a state) as a Referer. */
export const metadata: Metadata = {
  referrer: 'no-referrer',
};

/** Signed-out callback page: global look only, no fx components. */
export default function WaCallbackLayout({ children }: { children: ReactNode }) {
  return <FxComponentsOff>{children}</FxComponentsOff>;
}
