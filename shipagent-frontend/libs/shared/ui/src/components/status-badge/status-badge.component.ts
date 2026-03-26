/**
 * StatusBadgeComponent — Reusable status badge with semantic color mapping.
 *
 * Maps status values to badge CSS classes from the design system.
 * Renders using the `badge` and `badge-*` utility classes.
 */

import {
  ChangeDetectionStrategy,
  Component,
  Input,
  ViewEncapsulation,
} from '@angular/core';
import { NgClass } from '@angular/common';

export type BadgeStatus = 'success' | 'warning' | 'error' | 'info' | 'neutral';

@Component({
  selector: 'sa-status-badge',
  standalone: true,
  imports: [NgClass],
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `
    <span class="badge" [ngClass]="badgeClass">
      <ng-content />
    </span>
  `,
})
export class StatusBadgeComponent {
  /**
   * Status variant — controls the badge color and border.
   * Maps to badge-success, badge-warning, badge-error, badge-info, badge-neutral.
   */
  @Input() status: BadgeStatus = 'neutral';

  get badgeClass(): string {
    const map: Record<BadgeStatus, string> = {
      success: 'badge-success',
      warning: 'badge-warning',
      error: 'badge-error',
      info: 'badge-info',
      neutral: 'badge-neutral',
    };
    return map[this.status];
  }
}
