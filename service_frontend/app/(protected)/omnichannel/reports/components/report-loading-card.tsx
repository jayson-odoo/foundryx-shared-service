import { LoaderCircleIcon } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { useFx } from '@/hooks/use-fx';
import { FxCouldNotLoad, FxLoadingBox } from '../../components/fx-report-parts';

export interface ReportLoadingCardProps {
  errored?: boolean;
  /** Foundryx UIUX switch only: the couldn't-load state's "Try again". */
  onRetry?: () => void;
}

/** Shared loading/error placeholder for every report renderer (plan 30).
 *  Foundryx UIUX switch on: the playbook's loading shape and couldn't-load
 *  words with "Try again", in a box of the same height. */
export function ReportLoadingCard(props: ReportLoadingCardProps) {
  const fx = useFx();
  if (fx) {
    return props.errored ? (
      <FxCouldNotLoad what="this report" onRetry={props.onRetry} />
    ) : (
      <FxLoadingBox label="Loading the report" />
    );
  }
  return <ReportLoadingCardLegacy errored={props.errored} />;
}

function ReportLoadingCardLegacy({ errored = false }: { errored?: boolean }) {
  return (
    <Card>
      <CardContent className="flex h-56 items-center justify-center text-sm text-muted-foreground">
        {errored ? "Couldn't load this report." : <LoaderCircleIcon className="size-6 animate-spin" />}
      </CardContent>
    </Card>
  );
}
