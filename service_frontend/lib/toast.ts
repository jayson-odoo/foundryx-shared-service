/**
 * The ONE toast entry point (AC-DLA-51/D12). Every module reaches sonner
 * through here - direct `from 'sonner'` imports are banned outside this
 * file, `components/ui/sonner.tsx` (the `<Toaster>` mount) and
 * `components/platform/resource-actions/deferred-toast.tsx` (the grace-
 * window countdown toast, which needs `toast.custom`/`toast.dismiss`
 * directly and predates this wrapper - `lib/toast.inventory.test.ts` pins
 * all three).
 *
 * Durations: success/info/warning auto-dismiss at 4000ms; error stays until
 * the user closes it (`duration: Infinity` + `closeButton`) - an error the
 * user glanced past a moment too late must still be readable.
 */
import { toast as sonnerToast, type ExternalToast } from 'sonner';

type Message = Parameters<typeof sonnerToast>[0];

function success(message: Message, options?: ExternalToast): string | number {
  return sonnerToast.success(message, { duration: 4000, ...options });
}

function error(message: Message, options?: ExternalToast): string | number {
  return sonnerToast.error(message, { duration: Infinity, closeButton: true, ...options });
}

function info(message: Message, options?: ExternalToast): string | number {
  return sonnerToast.info(message, { duration: 4000, ...options });
}

function warning(message: Message, options?: ExternalToast): string | number {
  return sonnerToast.warning(message, { duration: 4000, ...options });
}

// Passthrough - callers already control their own duration/id for a custom
// JSX toast (e.g. the deferred-action countdown), a plain untyped toast
// with its own action/description (`message`), or a plain dismiss.
const custom = sonnerToast.custom;
const dismiss = sonnerToast.dismiss;
const message = sonnerToast.message;

export const toast = { success, error, info, warning, custom, dismiss, message };
