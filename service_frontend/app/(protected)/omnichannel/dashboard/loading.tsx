/**
 * Route-level skeleton for the Omnichannel Dashboard (nit, review round 1) -
 * the Reports sibling already had one, so a hard navigation to Dashboard was
 * the only report surface that flashed blank. Uses the shared
 * `ListPageSkeleton` primitive, never a bespoke placeholder.
 */
import { ListPageSkeleton } from '@/components/platform/skeletons/list-page-skeleton';

export default function Loading() {
  return <ListPageSkeleton />;
}
