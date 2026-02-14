/**
 * TEMPORARY BARREL — removal target: 2026-03-14
 *
 * All new imports should use individual component files directly:
 *   import { PreviewCard } from '@/components/command-center/PreviewCard';
 *   import { ProgressDisplay } from '@/components/command-center/ProgressDisplay';
 *   etc.
 *
 * After the removal date, update all consumers and delete this file.
 */

// Re-export icons that consumers import from this module
export {
  SendIcon, StopIcon, CheckIcon, XIcon, DownloadIcon, PackageIcon,
  ChevronDownIcon, EditIcon, GearIcon, MapPinIcon, UserIcon,
  ShoppingCartIcon,
} from '@/components/ui/icons';

// Utility functions (now in @/lib/utils — re-exported for compat)
export { formatCurrency, formatRelativeTime } from '@/lib/utils';

// Preview components
export { PreviewCard, InteractivePreviewCard, ShipmentDetails, ShipmentRow, ShipmentList } from './PreviewCard';
export type { ConfirmOptions } from './PreviewCard';

// Progress display
export { ProgressDisplay } from './ProgressDisplay';

// Completion artifact
export { CompletionArtifact, parseRefinedName } from './CompletionArtifact';

// Tool call chip
export { ToolCallChip } from './ToolCallChip';

// Messages and banners
export {
  SystemMessage, UserMessage, TypingIndicator, SettingsPopover,
  ActiveSourceBanner, InteractiveModeBanner, WelcomeMessage,
} from './messages';
