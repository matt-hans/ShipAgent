/**
 * Icon components — Angular SVG icon components.
 *
 * Port of ALL icons from `frontend/src/components/ui/icons.tsx`.
 * Each is a standalone Angular component with OnPush change detection.
 * ViewEncapsulation.None ensures no CSS scoping on pure SVG.
 *
 * Usage:
 *   imports: [SendIconComponent]
 *   <sa-icon-send class="w-4 h-4" />
 */

import {
  ChangeDetectionStrategy,
  Component,
  Input,
  ViewEncapsulation,
} from '@angular/core';

// ============================================================
// Base class pattern — all icons share the same boilerplate.
// ============================================================

/**
 * SendIconComponent — Paper plane send icon.
 */
@Component({
  selector: 'sa-icon-send',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <path d="M22 2L11 13" stroke-linecap="round" stroke-linejoin="round" />
    <path d="M22 2L15 22L11 13L2 9L22 2Z" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class SendIconComponent {
  @Input() class = '';
}

/**
 * StopIconComponent — Stop/square icon.
 */
@Component({
  selector: 'sa-icon-stop',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <rect x="6" y="6" width="12" height="12" rx="2" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class StopIconComponent {
  @Input() class = '';
}

/**
 * CheckIconComponent — Checkmark icon.
 */
@Component({
  selector: 'sa-icon-check',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <polyline points="20 6 9 17 4 12" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class CheckIconComponent {
  @Input() class = '';
}

/**
 * XIconComponent — Close/X icon.
 */
@Component({
  selector: 'sa-icon-x',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <line x1="18" y1="6" x2="6" y2="18" stroke-linecap="round" stroke-linejoin="round" />
    <line x1="6" y1="6" x2="18" y2="18" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class XIconComponent {
  @Input() class = '';
}

/**
 * DownloadIconComponent — Download arrow icon.
 */
@Component({
  selector: 'sa-icon-download',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" stroke-linecap="round" stroke-linejoin="round" />
    <polyline points="7 10 12 15 17 10" stroke-linecap="round" stroke-linejoin="round" />
    <line x1="12" y1="15" x2="12" y2="3" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class DownloadIconComponent {
  @Input() class = '';
}

/**
 * PackageIconComponent — 3D package/box icon.
 */
@Component({
  selector: 'sa-icon-package',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M16.5 9.4l-9-5.19" stroke-linecap="round" stroke-linejoin="round" />
    <path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z" stroke-linecap="round" stroke-linejoin="round" />
    <polyline points="3.27 6.96 12 12.01 20.73 6.96" stroke-linecap="round" stroke-linejoin="round" />
    <line x1="12" y1="22.08" x2="12" y2="12" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class PackageIconComponent {
  @Input() class = '';
}

/**
 * ChevronDownIconComponent — Downward chevron icon.
 */
@Component({
  selector: 'sa-icon-chevron-down',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <polyline points="6 9 12 15 18 9" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class ChevronDownIconComponent {
  @Input() class = '';
}

/**
 * ChevronUpIconComponent — Upward chevron icon.
 */
@Component({
  selector: 'sa-icon-chevron-up',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <polyline points="18 15 12 9 6 15" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class ChevronUpIconComponent {
  @Input() class = '';
}

/**
 * ChevronLeftIconComponent — Left chevron icon.
 */
@Component({
  selector: 'sa-icon-chevron-left',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <path d="M15 18l-6-6 6-6" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class ChevronLeftIconComponent {
  @Input() class = '';
}

/**
 * ChevronRightIconComponent — Right chevron icon.
 */
@Component({
  selector: 'sa-icon-chevron-right',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <path d="M9 18l6-6-6-6" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class ChevronRightIconComponent {
  @Input() class = '';
}

/**
 * EditIconComponent — Edit/pencil icon.
 */
@Component({
  selector: 'sa-icon-edit',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" stroke-linecap="round" stroke-linejoin="round" />
    <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class EditIconComponent {
  @Input() class = '';
}

/**
 * GearIconComponent — Settings/gear icon.
 */
@Component({
  selector: 'sa-icon-gear',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class GearIconComponent {
  @Input() class = '';
}

/**
 * MapPinIconComponent — Location pin icon.
 */
@Component({
  selector: 'sa-icon-map-pin',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z" stroke-linecap="round" stroke-linejoin="round" />
    <circle cx="12" cy="10" r="3" />
  </svg>`,
})
export class MapPinIconComponent {
  @Input() class = '';
}

/**
 * UserIconComponent — Single user/person icon.
 */
@Component({
  selector: 'sa-icon-user',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2" stroke-linecap="round" stroke-linejoin="round" />
    <circle cx="12" cy="7" r="4" />
  </svg>`,
})
export class UserIconComponent {
  @Input() class = '';
}

/**
 * SearchIconComponent — Magnifying glass search icon.
 */
@Component({
  selector: 'sa-icon-search',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <circle cx="11" cy="11" r="8" />
    <path d="M21 21l-4.35-4.35" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class SearchIconComponent {
  @Input() class = '';
}

/**
 * TrashIconComponent — Delete/trash icon.
 */
@Component({
  selector: 'sa-icon-trash',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <polyline points="3 6 5 6 21 6" stroke-linecap="round" stroke-linejoin="round" />
    <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" stroke-linecap="round" stroke-linejoin="round" />
    <line x1="10" y1="11" x2="10" y2="17" stroke-linecap="round" stroke-linejoin="round" />
    <line x1="14" y1="11" x2="14" y2="17" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class TrashIconComponent {
  @Input() class = '';
}

/**
 * PrinterIconComponent — Printer icon.
 */
@Component({
  selector: 'sa-icon-printer',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <polyline points="6 9 6 2 18 2 18 9" stroke-linecap="round" stroke-linejoin="round" />
    <path d="M6 18H4a2 2 0 01-2-2v-5a2 2 0 012-2h16a2 2 0 012 2v5a2 2 0 01-2 2h-2" stroke-linecap="round" stroke-linejoin="round" />
    <rect x="6" y="14" width="12" height="8" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class PrinterIconComponent {
  @Input() class = '';
}

/**
 * HardDriveIconComponent — Hard drive/storage icon.
 */
@Component({
  selector: 'sa-icon-hard-drive',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M22 12H2" stroke-linecap="round" stroke-linejoin="round" />
    <path d="M5.45 5.11L2 12v6a2 2 0 002 2h16a2 2 0 002-2v-6l-3.45-6.89A2 2 0 0016.76 4H7.24a2 2 0 00-1.79 1.11z" stroke-linecap="round" stroke-linejoin="round" />
    <line x1="6" y1="16" x2="6.01" y2="16" stroke-linecap="round" stroke-linejoin="round" />
    <line x1="10" y1="16" x2="10.01" y2="16" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class HardDriveIconComponent {
  @Input() class = '';
}

/**
 * CloudIconComponent — Cloud storage icon.
 */
@Component({
  selector: 'sa-icon-cloud',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M18 10h-1.26A8 8 0 109 20h9a5 5 0 000-10z" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class CloudIconComponent {
  @Input() class = '';
}

/**
 * EyeIconComponent — Show/visible eye icon.
 */
@Component({
  selector: 'sa-icon-eye',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" stroke-linecap="round" stroke-linejoin="round" />
    <circle cx="12" cy="12" r="3" />
  </svg>`,
})
export class EyeIconComponent {
  @Input() class = '';
}

/**
 * EyeOffIconComponent — Hide/invisible eye icon.
 */
@Component({
  selector: 'sa-icon-eye-off',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19m-6.72-1.07a3 3 0 11-4.24-4.24" stroke-linecap="round" stroke-linejoin="round" />
    <line x1="1" y1="1" x2="23" y2="23" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class EyeOffIconComponent {
  @Input() class = '';
}

/**
 * ShoppingCartIconComponent — Shopping cart icon.
 */
@Component({
  selector: 'sa-icon-shopping-cart',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <circle cx="9" cy="21" r="1" />
    <circle cx="20" cy="21" r="1" />
    <path d="M1 1h4l2.68 13.39a2 2 0 002 1.61h9.72a2 2 0 002-1.61L23 6H6" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class ShoppingCartIconComponent {
  @Input() class = '';
}

/**
 * ArrowLeftIconComponent — Left arrow icon.
 */
@Component({
  selector: 'sa-icon-arrow-left',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <line x1="19" y1="12" x2="5" y2="12" stroke-linecap="round" stroke-linejoin="round" />
    <polyline points="12 19 5 12 12 5" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class ArrowLeftIconComponent {
  @Input() class = '';
}

/**
 * ArrowRightIconComponent — Right arrow icon.
 */
@Component({
  selector: 'sa-icon-arrow-right',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <line x1="5" y1="12" x2="19" y2="12" stroke-linecap="round" stroke-linejoin="round" />
    <polyline points="12 5 19 12 12 19" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class ArrowRightIconComponent {
  @Input() class = '';
}

/**
 * PlusIconComponent — Plus/add icon.
 */
@Component({
  selector: 'sa-icon-plus',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <line x1="12" y1="5" x2="12" y2="19" stroke-linecap="round" stroke-linejoin="round" />
    <line x1="5" y1="12" x2="19" y2="12" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class PlusIconComponent {
  @Input() class = '';
}

/**
 * MinusIconComponent — Minus/subtract icon.
 */
@Component({
  selector: 'sa-icon-minus',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <line x1="5" y1="12" x2="19" y2="12" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class MinusIconComponent {
  @Input() class = '';
}

/**
 * XCircleIconComponent — Circle with X icon (error/close).
 */
@Component({
  selector: 'sa-icon-x-circle',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <circle cx="12" cy="12" r="10" />
    <line x1="15" y1="9" x2="9" y2="15" stroke-linecap="round" stroke-linejoin="round" />
    <line x1="9" y1="9" x2="15" y2="15" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class XCircleIconComponent {
  @Input() class = '';
}

/**
 * CheckCircleIconComponent — Circle with checkmark icon (success).
 */
@Component({
  selector: 'sa-icon-check-circle',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <circle cx="12" cy="12" r="10" />
    <polyline points="9 12 11 14 15 10" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class CheckCircleIconComponent {
  @Input() class = '';
}

/**
 * PlayIconComponent — Play triangle icon.
 */
@Component({
  selector: 'sa-icon-play',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <polygon points="5 3 19 12 5 21 5 3" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class PlayIconComponent {
  @Input() class = '';
}

/**
 * LoadingIconComponent — Spinning loader arc icon.
 */
@Component({
  selector: 'sa-icon-loading',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M21 12a9 9 0 1 1-6.219-8.56" />
  </svg>`,
})
export class LoadingIconComponent {
  @Input() class = '';
}

/**
 * AlertIconComponent — Alert/info circle icon.
 */
@Component({
  selector: 'sa-icon-alert',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <circle cx="12" cy="12" r="10" />
    <line x1="12" y1="8" x2="12" y2="12" />
    <line x1="12" y1="16" x2="12.01" y2="16" />
  </svg>`,
})
export class AlertIconComponent {
  @Input() class = '';
}

/**
 * AlertTriangleIconComponent — Warning triangle icon.
 */
@Component({
  selector: 'sa-icon-alert-triangle',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" stroke-linecap="round" stroke-linejoin="round" />
    <line x1="12" y1="9" x2="12" y2="13" stroke-linecap="round" stroke-linejoin="round" />
    <line x1="12" y1="17" x2="12.01" y2="17" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class AlertTriangleIconComponent {
  @Input() class = '';
}

/**
 * FileIconComponent — Generic file icon.
 */
@Component({
  selector: 'sa-icon-file',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" stroke-linecap="round" stroke-linejoin="round" />
    <polyline points="14 2 14 8 20 8" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class FileIconComponent {
  @Input() class = '';
}

/**
 * FileTextIconComponent — File with text lines icon.
 */
@Component({
  selector: 'sa-icon-file-text',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" stroke-linecap="round" stroke-linejoin="round" />
    <polyline points="14 2 14 8 20 8" stroke-linecap="round" stroke-linejoin="round" />
    <line x1="16" y1="13" x2="8" y2="13" stroke-linecap="round" stroke-linejoin="round" />
    <line x1="16" y1="17" x2="8" y2="17" stroke-linecap="round" stroke-linejoin="round" />
    <polyline points="10 9 9 9 8 9" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class FileTextIconComponent {
  @Input() class = '';
}

/**
 * DatabaseIconComponent — Database/cylinder stack icon.
 */
@Component({
  selector: 'sa-icon-database',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <ellipse cx="12" cy="6" rx="8" ry="3" />
    <path d="M4 6v6c0 1.657 3.582 3 8 3s8-1.343 8-3V6" />
    <path d="M4 12v6c0 1.657 3.582 3 8 3s8-1.343 8-3v-6" />
  </svg>`,
})
export class DatabaseIconComponent {
  @Input() class = '';
}

/**
 * HistoryIconComponent — Clock with history icon.
 */
@Component({
  selector: 'sa-icon-history',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <circle cx="12" cy="12" r="10" />
    <polyline points="12,6 12,12 16,14" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class HistoryIconComponent {
  @Input() class = '';
}

/**
 * PhoneIconComponent — Phone icon.
 */
@Component({
  selector: 'sa-icon-phone',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 014.11 2h3a2 2 0 012 1.72 12.84 12.84 0 00.7 2.81 2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45 12.84 12.84 0 002.81.7A2 2 0 0122 16.92z" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class PhoneIconComponent {
  @Input() class = '';
}

/**
 * UploadIconComponent — Upload arrow icon.
 */
@Component({
  selector: 'sa-icon-upload',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" stroke-linecap="round" stroke-linejoin="round" />
    <polyline points="17 8 12 3 7 8" stroke-linecap="round" stroke-linejoin="round" />
    <line x1="12" y1="3" x2="12" y2="15" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class UploadIconComponent {
  @Input() class = '';
}

/**
 * CopyIconComponent — Copy/duplicate icon.
 */
@Component({
  selector: 'sa-icon-copy',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
    <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
  </svg>`,
})
export class CopyIconComponent {
  @Input() class = '';
}

/**
 * InfoIconComponent — Info circle icon (filled).
 */
@Component({
  selector: 'sa-icon-info',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 16 16" fill="currentColor">
    <path d="M8 15A7 7 0 1 1 8 1a7 7 0 0 1 0 14zm0 1A8 8 0 1 0 8 0a8 8 0 0 0 0 16z"/>
    <path d="m8.93 6.588-2.29.287-.082.38.45.083c.294.07.352.176.288.469l-.738 3.468c-.194.897.105 1.319.808 1.319.545 0 1.178-.252 1.465-.598l.088-.416c-.2.176-.492.246-.686.246-.275 0-.375-.193-.304-.533L8.93 6.588zM9 4.5a1 1 0 1 1-2 0 1 1 0 0 1 2 0z"/>
  </svg>`,
})
export class InfoIconComponent {
  @Input() class = '';
}

/**
 * RefreshIconComponent — Refresh/reload arrows icon.
 */
@Component({
  selector: 'sa-icon-refresh',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <polyline points="1 4 1 10 7 10" stroke-linecap="round" stroke-linejoin="round" />
    <path d="M3.51 15a9 9 0 102.13-9.36L1 10" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class RefreshIconComponent {
  @Input() class = '';
}

/**
 * ExternalLinkIconComponent — External link arrow icon.
 */
@Component({
  selector: 'sa-icon-external-link',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" stroke-linecap="round" stroke-linejoin="round" />
    <polyline points="15 3 21 3 21 9" stroke-linecap="round" stroke-linejoin="round" />
    <line x1="10" y1="14" x2="21" y2="3" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class ExternalLinkIconComponent {
  @Input() class = '';
}

/**
 * LinkIconComponent — Chain link icon.
 */
@Component({
  selector: 'sa-icon-link',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71" stroke-linecap="round" stroke-linejoin="round" />
    <path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class LinkIconComponent {
  @Input() class = '';
}

/**
 * LockIconComponent — Closed padlock icon.
 */
@Component({
  selector: 'sa-icon-lock',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
    <path d="M7 11V7a5 5 0 0110 0v4" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class LockIconComponent {
  @Input() class = '';
}

/**
 * UnlockIconComponent — Open padlock icon.
 */
@Component({
  selector: 'sa-icon-unlock',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
    <path d="M7 11V7a5 5 0 019.9-1" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class UnlockIconComponent {
  @Input() class = '';
}

/**
 * TruckIconComponent — Delivery truck icon.
 */
@Component({
  selector: 'sa-icon-truck',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <rect x="1" y="3" width="15" height="13" />
    <polygon points="16 8 20 8 23 11 23 16 16 16 16 8" />
    <circle cx="5.5" cy="18.5" r="2.5" />
    <circle cx="18.5" cy="18.5" r="2.5" />
  </svg>`,
})
export class TruckIconComponent {
  @Input() class = '';
}

/**
 * GlobeIconComponent — Globe/world icon.
 */
@Component({
  selector: 'sa-icon-globe',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <circle cx="12" cy="12" r="10" />
    <line x1="2" y1="12" x2="22" y2="12" stroke-linecap="round" stroke-linejoin="round" />
    <path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class GlobeIconComponent {
  @Input() class = '';
}

/**
 * CalendarIconComponent — Calendar icon.
 */
@Component({
  selector: 'sa-icon-calendar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
    <line x1="16" y1="2" x2="16" y2="6" stroke-linecap="round" stroke-linejoin="round" />
    <line x1="8" y1="2" x2="8" y2="6" stroke-linecap="round" stroke-linejoin="round" />
    <line x1="3" y1="10" x2="21" y2="10" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class CalendarIconComponent {
  @Input() class = '';
}

/**
 * ClockIconComponent — Clock/time icon.
 */
@Component({
  selector: 'sa-icon-clock',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <circle cx="12" cy="12" r="10" />
    <polyline points="12 6 12 12 16 14" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class ClockIconComponent {
  @Input() class = '';
}

/**
 * StarIconComponent — Star/favorite icon.
 */
@Component({
  selector: 'sa-icon-star',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class StarIconComponent {
  @Input() class = '';
}

/**
 * TagIconComponent — Label/tag icon.
 */
@Component({
  selector: 'sa-icon-tag',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M20.59 13.41l-7.17 7.17a2 2 0 01-2.83 0L2 12V2h10l8.59 8.59a2 2 0 010 2.82z" stroke-linecap="round" stroke-linejoin="round" />
    <line x1="7" y1="7" x2="7.01" y2="7" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class TagIconComponent {
  @Input() class = '';
}

/**
 * FilterIconComponent — Funnel/filter icon.
 */
@Component({
  selector: 'sa-icon-filter',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class FilterIconComponent {
  @Input() class = '';
}

/**
 * LayoutIconComponent — Grid layout icon.
 */
@Component({
  selector: 'sa-icon-layout',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <rect x="3" y="3" width="7" height="7" />
    <rect x="14" y="3" width="7" height="7" />
    <rect x="14" y="14" width="7" height="7" />
    <rect x="3" y="14" width="7" height="7" />
  </svg>`,
})
export class LayoutIconComponent {
  @Input() class = '';
}

/**
 * MenuIconComponent — Hamburger menu icon.
 */
@Component({
  selector: 'sa-icon-menu',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <line x1="3" y1="12" x2="21" y2="12" stroke-linecap="round" stroke-linejoin="round" />
    <line x1="3" y1="6" x2="21" y2="6" stroke-linecap="round" stroke-linejoin="round" />
    <line x1="3" y1="18" x2="21" y2="18" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class MenuIconComponent {
  @Input() class = '';
}

/**
 * MoreHorizontalIconComponent — Three horizontal dots (kebab menu).
 */
@Component({
  selector: 'sa-icon-more-horizontal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <circle cx="12" cy="12" r="1" fill="currentColor" />
    <circle cx="19" cy="12" r="1" fill="currentColor" />
    <circle cx="5" cy="12" r="1" fill="currentColor" />
  </svg>`,
})
export class MoreHorizontalIconComponent {
  @Input() class = '';
}

/**
 * MoreVerticalIconComponent — Three vertical dots (ellipsis menu).
 */
@Component({
  selector: 'sa-icon-more-vertical',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <circle cx="12" cy="12" r="1" fill="currentColor" />
    <circle cx="12" cy="5" r="1" fill="currentColor" />
    <circle cx="12" cy="19" r="1" fill="currentColor" />
  </svg>`,
})
export class MoreVerticalIconComponent {
  @Input() class = '';
}

/**
 * ZapIconComponent — Lightning bolt / fast action icon.
 */
@Component({
  selector: 'sa-icon-zap',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class ZapIconComponent {
  @Input() class = '';
}

/**
 * BookOpenIconComponent — Open book icon.
 */
@Component({
  selector: 'sa-icon-book-open',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M2 3h6a4 4 0 014 4v14a3 3 0 00-3-3H2z" stroke-linecap="round" stroke-linejoin="round" />
    <path d="M22 3h-6a4 4 0 00-4 4v14a3 3 0 013-3h7z" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class BookOpenIconComponent {
  @Input() class = '';
}

/**
 * TerminalIconComponent — Command line terminal icon.
 */
@Component({
  selector: 'sa-icon-terminal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <polyline points="4 17 10 11 4 5" stroke-linecap="round" stroke-linejoin="round" />
    <line x1="12" y1="19" x2="20" y2="19" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class TerminalIconComponent {
  @Input() class = '';
}

/**
 * MessageSquareIconComponent — Chat message bubble icon.
 */
@Component({
  selector: 'sa-icon-message-square',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class MessageSquareIconComponent {
  @Input() class = '';
}

/**
 * SparklesIconComponent — AI/sparkles/magic icon.
 */
@Component({
  selector: 'sa-icon-sparkles',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M12 3l1.5 4.5L18 9l-4.5 1.5L12 15l-1.5-4.5L6 9l4.5-1.5L12 3z" stroke-linecap="round" stroke-linejoin="round" />
    <path d="M5 18l.75 2.25L8 21l-2.25.75L5 24l-.75-2.25L2 21l2.25-.75L5 18z" stroke-linecap="round" stroke-linejoin="round" />
    <path d="M19 4l.5 1.5L21 6l-1.5.5L19 8l-.5-1.5L17 6l1.5-.5L19 4z" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class SparklesIconComponent {
  @Input() class = '';
}

/**
 * KeyIconComponent — Key/credential icon.
 */
@Component({
  selector: 'sa-icon-key',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 11-7.778 7.778 5.5 5.5 0 017.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class KeyIconComponent {
  @Input() class = '';
}

/**
 * ShieldIconComponent — Security shield icon.
 */
@Component({
  selector: 'sa-icon-shield',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class ShieldIconComponent {
  @Input() class = '';
}

/**
 * BellIconComponent — Notification bell icon.
 */
@Component({
  selector: 'sa-icon-bell',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" stroke-linecap="round" stroke-linejoin="round" />
    <path d="M13.73 21a2 2 0 01-3.46 0" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class BellIconComponent {
  @Input() class = '';
}

/**
 * SlidersIconComponent — Horizontal sliders/settings icon.
 */
@Component({
  selector: 'sa-icon-sliders',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <line x1="4" y1="21" x2="4" y2="14" stroke-linecap="round" stroke-linejoin="round" />
    <line x1="4" y1="10" x2="4" y2="3" stroke-linecap="round" stroke-linejoin="round" />
    <line x1="12" y1="21" x2="12" y2="12" stroke-linecap="round" stroke-linejoin="round" />
    <line x1="12" y1="8" x2="12" y2="3" stroke-linecap="round" stroke-linejoin="round" />
    <line x1="20" y1="21" x2="20" y2="16" stroke-linecap="round" stroke-linejoin="round" />
    <line x1="20" y1="12" x2="20" y2="3" stroke-linecap="round" stroke-linejoin="round" />
    <line x1="1" y1="14" x2="7" y2="14" stroke-linecap="round" stroke-linejoin="round" />
    <line x1="9" y1="8" x2="15" y2="8" stroke-linecap="round" stroke-linejoin="round" />
    <line x1="17" y1="16" x2="23" y2="16" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class SlidersIconComponent {
  @Input() class = '';
}

/**
 * UsersIconComponent — Multiple users/group icon.
 */
@Component({
  selector: 'sa-icon-users',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" stroke-linecap="round" stroke-linejoin="round" />
    <circle cx="9" cy="7" r="4" />
    <path d="M23 21v-2a4 4 0 00-3-3.87" stroke-linecap="round" stroke-linejoin="round" />
    <path d="M16 3.13a4 4 0 010 7.75" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class UsersIconComponent {
  @Input() class = '';
}

/**
 * ArchiveIconComponent — Archive/box icon.
 */
@Component({
  selector: 'sa-icon-archive',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <polyline points="21 8 21 21 3 21 3 8" stroke-linecap="round" stroke-linejoin="round" />
    <rect x="1" y="3" width="22" height="5" />
    <line x1="10" y1="12" x2="14" y2="12" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class ArchiveIconComponent {
  @Input() class = '';
}

/**
 * LayersIconComponent — Layers/stack icon (for data sources).
 */
@Component({
  selector: 'sa-icon-layers',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <polygon points="12 2 2 7 12 12 22 7 12 2" stroke-linecap="round" stroke-linejoin="round" />
    <polyline points="2 17 12 22 22 17" stroke-linecap="round" stroke-linejoin="round" />
    <polyline points="2 12 12 17 22 12" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class LayersIconComponent {
  @Input() class = '';
}

/**
 * CreditCardIconComponent — Payment/credit card icon.
 */
@Component({
  selector: 'sa-icon-credit-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <rect x="1" y="4" width="22" height="16" rx="2" ry="2" />
    <line x1="1" y1="10" x2="23" y2="10" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class CreditCardIconComponent {
  @Input() class = '';
}

/**
 * DollarSignIconComponent — Dollar sign / cost icon.
 */
@Component({
  selector: 'sa-icon-dollar-sign',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<svg [attr.class]="class" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <line x1="12" y1="1" x2="12" y2="23" stroke-linecap="round" stroke-linejoin="round" />
    <path d="M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6" stroke-linecap="round" stroke-linejoin="round" />
  </svg>`,
})
export class DollarSignIconComponent {
  @Input() class = '';
}

// ============================================================
// Export list - all icon components
// ============================================================
export const ALL_ICON_COMPONENTS = [
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
] as const;
