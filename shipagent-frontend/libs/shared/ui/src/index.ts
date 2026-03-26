// @shipagent/shared-ui — Complete UI primitives, design tokens, icons, pipes, directives

// ============================================================
// Utilities
// ============================================================
export { cn } from './utils/cn';

// ============================================================
// Icon Components (50+ SVG icons, OnPush, standalone)
// ============================================================
export {
  ALL_ICON_COMPONENTS,
  SendIconComponent,
  StopIconComponent,
  CheckIconComponent,
  XIconComponent,
  DownloadIconComponent,
  PackageIconComponent,
  ChevronDownIconComponent,
  ChevronUpIconComponent,
  ChevronLeftIconComponent,
  ChevronRightIconComponent,
  EditIconComponent,
  GearIconComponent,
  MapPinIconComponent,
  UserIconComponent,
  SearchIconComponent,
  TrashIconComponent,
  PrinterIconComponent,
  HardDriveIconComponent,
  CloudIconComponent,
  EyeIconComponent,
  EyeOffIconComponent,
  ShoppingCartIconComponent,
  ArrowLeftIconComponent,
  ArrowRightIconComponent,
  PlusIconComponent,
  MinusIconComponent,
  XCircleIconComponent,
  CheckCircleIconComponent,
  PlayIconComponent,
  LoadingIconComponent,
  AlertIconComponent,
  AlertTriangleIconComponent,
  FileIconComponent,
  FileTextIconComponent,
  DatabaseIconComponent,
  HistoryIconComponent,
  PhoneIconComponent,
  UploadIconComponent,
  CopyIconComponent,
  InfoIconComponent,
  RefreshIconComponent,
  ExternalLinkIconComponent,
  LinkIconComponent,
  LockIconComponent,
  UnlockIconComponent,
  TruckIconComponent,
  GlobeIconComponent,
  CalendarIconComponent,
  ClockIconComponent,
  StarIconComponent,
  TagIconComponent,
  FilterIconComponent,
  LayoutIconComponent,
  MenuIconComponent,
  MoreHorizontalIconComponent,
  MoreVerticalIconComponent,
  ZapIconComponent,
  BookOpenIconComponent,
  TerminalIconComponent,
  MessageSquareIconComponent,
  SparklesIconComponent,
  KeyIconComponent,
  ShieldIconComponent,
  BellIconComponent,
  SlidersIconComponent,
  UsersIconComponent,
  ArchiveIconComponent,
  LayersIconComponent,
  CreditCardIconComponent,
  DollarSignIconComponent,
} from './components/icons/index';

// ============================================================
// Brand Icon Components
// ============================================================
export {
  ALL_BRAND_ICON_COMPONENTS,
  ShopifyIconComponent,
  AmazonIconComponent,
  WooCommerceIconComponent,
  SAPIconComponent,
  OracleIconComponent,
  DataSourceIconComponent,
} from './components/brand-icons/index';

// ============================================================
// ShipAgent Logo Components
// ============================================================
export {
  ShipAgentLogoComponent,
  ShipAgentIconComponent,
} from './components/shipagent-logo/shipagent-logo.component';

// ============================================================
// UI Components
// ============================================================
export { CopyButtonComponent } from './components/copy-button/copy-button.component';
export { StatusBadgeComponent } from './components/status-badge/status-badge.component';
export type { BadgeStatus } from './components/status-badge/status-badge.component';

// ============================================================
// Pipes (standalone, pure)
// ============================================================
export { FormatCurrencyPipe } from './pipes/format-currency.pipe';
export { RelativeTimePipe } from './pipes/relative-time.pipe';
export { TimeAgoPipe } from './pipes/time-ago.pipe';

// ============================================================
// Directives (standalone)
// ============================================================
export { MirrorSyncDirective } from './directives/mirror-sync.directive';
