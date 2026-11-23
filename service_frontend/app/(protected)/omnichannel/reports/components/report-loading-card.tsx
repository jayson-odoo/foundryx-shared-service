import { LoaderCircleIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { useFx } from '@/hooks/use-fx';
import { FxCouldNotLoad, FxLoadingBox } from '../../components/fx-report-parts';

export interface ReportLoadingCardProps {
  errored?: boolean;
  /** The couldn't-load state's "Try again". */
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
  return <ReportLoadingCardLegacy errored={props.errored} onRetry={props.onRetry} />;
}

function ReportLoadingCardLegacy({ errored = false, onRetry }: ReportLoadingCardProps) {
  return (
    <Card>
      <CardContent className="flex h-56 items-center justify-center gap-2 text-sm text-muted-foreground">
        {errored ? (
          <>
            <span role="alert">Couldn&apos;t load this report.</span>
            {onRetry && (
              <Button mode="link" size="sm" onClick={onRetry}>
                Try again
              </Button>
            )}
          </>
        ) : (
          <LoaderCircleIcon className="size-6 animate-spin" />
        )}
      </CardContent>
    </Card>
  );
}
