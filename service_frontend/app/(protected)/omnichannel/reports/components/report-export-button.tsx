'use client';

import { useMemo } from 'react';
import { Button } from '@/components/ui/button';
import { useFx } from '@/hooks/use-fx';
import {
  useRegisterOtherActions,
  type FxOtherActionSpec,
} from '@/components/fx/actions/page-actions-context';

export interface ReportExportButtonProps {
  disabled: boolean;
  exporting: boolean;
  onExport: () => void;
  /** The report's name, for the icon action's label ("Export Messages CSV"). */
  reportLabel?: string;
}

/**
 * The reports page's Export. Switch off: today's outline button, unchanged.
 * Foundryx UIUX switch on (playbook 0.71.0 "Other Actions are icon
 * buttons"): a CSV-down icon action in the page header, the same export.
 */
export function ReportExportButton(props: ReportExportButtonProps) {
  return useFx() ? <FxReportExport {...props} /> : <ReportExportButtonLegacy {...props} />;
}

function ReportExportButtonLegacy({ disabled, exporting, onExport }: ReportExportButtonProps) {
  return (
    <Button variant="outline" size="sm" disabled={disabled} onClick={onExport}>
      {exporting ? 'Exporting...' : 'Export'}
    </Button>
  );
}

function FxReportExport({ disabled, exporting, onExport, reportLabel }: ReportExportButtonProps) {
  const actions = useMemo<FxOtherActionSpec[]>(
    () => [
      {
        id: 'report-export',
        label: reportLabel ? `Export ${reportLabel} CSV` : 'Export CSV',
        icon: 'csv-down',
        onClick: onExport,
        disabledReason: exporting ? 'Exporting now.' : disabled ? 'Pick a workspace first.' : undefined,
      },
    ],
    [reportLabel, onExport, exporting, disabled],
  );
  useRegisterOtherActions(actions);
  return null;
}
