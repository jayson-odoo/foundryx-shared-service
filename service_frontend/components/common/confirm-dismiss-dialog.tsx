import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { useFx } from '@/hooks/use-fx';
import { FxDiscardDialog } from '@/components/fx/actions/confirm-dialog';

interface ConfirmDismissDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
  onCancel: () => void;
  /** Foundryx UIUX switch only: the record named in "Discard changes to
   *  <name>?". Ignored with the switch off. */
  name?: string;
}

/**
 * Foundryx UIUX switch on (playbook-uiux.md): "Discard changes to <name>?"
 * with "Keep editing" and a red single-click "Discard changes". Off: the
 * original dialog, markup unchanged.
 */
export const ConfirmDismissDialog = (props: ConfirmDismissDialogProps) => {
  return useFx() ? (
    <FxDiscardDialog
      open={props.open}
      name={props.name}
      onKeep={() => {
        props.onCancel();
        props.onOpenChange(false);
      }}
      onDiscard={() => {
        props.onConfirm();
        props.onOpenChange(false);
      }}
    />
  ) : (
    <ConfirmDismissDialogLegacy {...props} />
  );
};

const ConfirmDismissDialogLegacy = ({
  open,
  onOpenChange,
  onConfirm,
  onCancel,
}: ConfirmDismissDialogProps) => {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent className="md:max-w-[375px]">
        <AlertDialogHeader>
          <AlertDialogTitle>Discard changes?</AlertDialogTitle>
          <AlertDialogDescription>
            You have unsaved changes. Are you sure you want to close this
            dialog?
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={onCancel}>Cancel</AlertDialogCancel>
          <AlertDialogAction onClick={onConfirm}>
            Discard changes
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
};
