/**
 * TEMPORARY BARREL — removal target: 2026-03-14
 *
 * All new imports should use individual component files directly:
 *   import { DataSourceSection } from '@/components/sidebar/DataSourcePanel';
 *   import { JobHistorySection } from '@/components/sidebar/JobHistoryPanel';
 *   etc.
 *
 * After the removal date, update all consumers and delete this file.
 */

// Re-export icons that consumers import from this module
export {
  ChevronIcon, SearchIcon, HardDriveIcon, CloudIcon,
  EyeIcon, EyeOffIcon, TrashIcon, PrinterIcon, HistoryIcon,
} from '@/components/ui/icons';
export { ShopifyIcon, DataSourceIcon } from '@/components/ui/brand-icons';

// Data source panel
export { DataSourceSection, extractFileName } from './DataSourcePanel';

// Job history panel
export { JobHistorySection, StatusBadge } from './JobHistoryPanel';
