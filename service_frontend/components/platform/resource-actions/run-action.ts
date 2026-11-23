import { toast } from '@/lib/toast';
import type { ResourceAction, ResourceActionRuntime } from '@/components/platform/resource-list/types';

/**
 * Runs an action's own `run` and reports a failure the way every other failed
 * action in the menus does: an error toast with the server's reason (the
 * `ApiError` message carries the response `detail`), or the generic line when
 * there is none. The menus start actions fire-and-forget (`void run(action)`,
 * after the confirm dialog has already closed), so a rejection left here would
 * surface nowhere on screen and land as an unhandled promise rejection.
 */
export async function runResourceAction<T>(
  action: ResourceAction<T>,
  rows: T[],
  runtime: ResourceActionRuntime,
): Promise<void> {
  try {
    await action.run?.(rows, runtime);
  } catch (error) {
    toast.error(error instanceof Error && error.message ? error.message : 'The action failed.');
  }
}
