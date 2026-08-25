/**
 * Shared lucide icon registry for workflow nodes (plan sprint-2/09) - the
 * palette and the canvas node both resolve `catalog.icon` through this map so
 * the names stay in one place. Add a catalog `icon` → add it here.
 */
import {
  Activity,
  ArrowLeftRight,
  CalendarClock,
  FilePenLine,
  FilePlus2,
  FileX,
  GitBranch,
  HardDriveDownload,
  HardDriveUpload,
  Mail,
  MousePointerClick,
  PencilLine,
  Trash2,
  Workflow as WorkflowIcon,
  Zap,
  type LucideIcon,
} from 'lucide-react';

export const WORKFLOW_NODE_ICONS: Record<string, LucideIcon> = {
  MousePointerClick,
  Mail,
  GitBranch,
  Zap,
  Workflow: WorkflowIcon,
  FilePlus2,
  FilePenLine,
  FileX,
  PencilLine,
  Activity,
  CalendarClock,
  HardDriveUpload,
  HardDriveDownload,
  Trash2,
  ArrowLeftRight,
};
