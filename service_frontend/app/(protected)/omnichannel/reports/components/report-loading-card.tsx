import { LoaderCircleIcon } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';

/** Shared loading/error placeholder for every report renderer (plan 30). */
export function ReportLoadingCard({ errored = false }: { errored?: boolean }) {
  return (
    <Card>
      <CardContent className="flex h-56 items-center justify-center text-sm text-muted-foreground">
        {errored ? "Couldn't load this report." : <LoaderCircleIcon className="size-6 animate-spin" />}
      </CardContent>
    </Card>
  );
}
