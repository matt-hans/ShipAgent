/**
 * TrackingCardComponent
 *
 * Port of React TrackingCard.tsx.
 * Renders UPS package tracking results with activity timeline.
 * Supports collapsible activities (3 shown by default).
 * Domain color: tracking/blue via card-domain-tracking CSS class.
 */

import {
  Component,
  Input,
  ChangeDetectionStrategy,
  signal,
  computed,
} from '@angular/core';
import {
  SearchIconComponent,
  AlertIconComponent,
  CheckIconComponent,
  PackageIconComponent,
  ChevronDownIconComponent,
} from '@shipagent/shared-ui';
import type { TrackingResult } from '@shipagent/shared-types';

const COLLAPSED_ACTIVITY_COUNT = 3;

interface StatusInfo {
  label: string;
  badgeClass: string;
  heroGradientClass: string;
  heroBorderClass: string;
  iconColorClass: string;
  iconType: 'check' | 'alert' | 'package';
}

function getStatusInfo(status: string): StatusInfo {
  const upper = (status || '').toUpperCase();

  if (upper.includes('DELIVER')) {
    return {
      label: 'DELIVERED',
      badgeClass: 'badge-success',
      heroGradientClass: 'from-[oklch(var(--color-success)/0.10)] to-[oklch(var(--color-success)/0.05)]',
      heroBorderClass: 'border-[oklch(var(--color-success)/0.20)]',
      iconColorClass: 'text-success',
      iconType: 'check',
    };
  }
  if (upper.includes('EXCEPTION') || upper.includes('ERROR')) {
    return {
      label: 'EXCEPTION',
      badgeClass: 'badge-warning',
      heroGradientClass: 'from-warning/10 to-warning/5',
      heroBorderClass: 'border-warning/20',
      iconColorClass: 'text-warning',
      iconType: 'alert',
    };
  }
  if (upper.includes('TRANSIT') || upper.includes('IN TRANSIT')) {
    return {
      label: 'IN TRANSIT',
      badgeClass: 'badge-info',
      heroGradientClass: 'from-[var(--color-domain-tracking)]/10 to-[var(--color-domain-tracking)]/5',
      heroBorderClass: 'border-[var(--color-domain-tracking)]/20',
      iconColorClass: 'text-[var(--color-domain-tracking)]',
      iconType: 'package',
    };
  }
  if (upper.includes('PICKUP') || upper.includes('PICKED UP')) {
    return {
      label: 'PICKED UP',
      badgeClass: 'badge-info',
      heroGradientClass: 'from-[var(--color-domain-tracking)]/10 to-[var(--color-domain-tracking)]/5',
      heroBorderClass: 'border-[var(--color-domain-tracking)]/20',
      iconColorClass: 'text-[var(--color-domain-tracking)]',
      iconType: 'package',
    };
  }
  if (upper.includes('LABEL') || upper.includes('CREATED')) {
    return {
      label: 'LABEL CREATED',
      badgeClass: 'badge-neutral',
      heroGradientClass: 'from-[var(--color-domain-tracking)]/10 to-[var(--color-domain-tracking)]/5',
      heroBorderClass: 'border-[var(--color-domain-tracking)]/20',
      iconColorClass: 'text-[var(--color-domain-tracking)]',
      iconType: 'package',
    };
  }
  return {
    label: status || 'UNKNOWN',
    badgeClass: 'badge-neutral',
    heroGradientClass: 'from-[var(--color-domain-tracking)]/10 to-[var(--color-domain-tracking)]/5',
    heroBorderClass: 'border-[var(--color-domain-tracking)]/20',
    iconColorClass: 'text-[var(--color-domain-tracking)]',
    iconType: 'package',
  };
}

/** Format YYYYMMDD to readable "Mon DD, YYYY". */
function formatDateReadable(date: string): string {
  if (!date || date.length !== 8) return date || '';
  const d = new Date(
    +date.slice(0, 4),
    +date.slice(4, 6) - 1,
    +date.slice(6, 8),
  );
  return d.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

/** Format HHMMSS to HH:MM. */
function formatActivityTime(time: string): string {
  if (!time || time.length < 4) return time || '';
  return `${time.slice(0, 2)}:${time.slice(2, 4)}`;
}

@Component({
  selector: 'app-tracking-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    SearchIconComponent,
    AlertIconComponent,
    CheckIconComponent,
    PackageIconComponent,
    ChevronDownIconComponent,
  ],
  template: `
    <div class="card-premium p-4 space-y-3 border-l-4 card-domain-tracking">
      <!-- Header -->
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-2">
          <sa-icon-search class="w-4 h-4 text-[var(--color-domain-tracking)]" />
          <h4 class="text-sm font-medium text-foreground">Package Tracking</h4>
        </div>
        <span class="badge {{ statusInfo.badgeClass }}">{{ statusInfo.label }}</span>
      </div>

      <!-- Status hero -->
      @if (statusDisplay) {
        <div
          class="rounded-lg p-3 bg-gradient-to-r border {{ statusInfo.heroGradientClass }} {{ statusInfo.heroBorderClass }}"
        >
          <div class="flex items-center gap-2.5">
            @if (statusInfo.iconType === 'check') {
              <sa-icon-check class="w-5 h-5 {{ statusInfo.iconColorClass }}" />
            } @else if (statusInfo.iconType === 'alert') {
              <sa-icon-alert class="w-5 h-5 {{ statusInfo.iconColorClass }}" />
            } @else {
              <sa-icon-package class="w-5 h-5 {{ statusInfo.iconColorClass }}" />
            }
            <div>
              <p class="text-sm font-medium text-foreground">{{ statusDisplay }}</p>
              @if (data.deliveryDate) {
                <p class="text-xs text-muted-foreground mt-0.5">
                  {{ isDelivered ? 'Delivered' : 'Expected' }} {{ formatDate(data.deliveryDate) }}
                </p>
              }
            </div>
          </div>
        </div>
      }

      <!-- Tracking number -->
      <div class="flex items-center gap-2 text-xs">
        <span class="text-muted-foreground">Tracking:</span>
        <code class="px-1.5 py-0.5 rounded bg-muted font-mono text-foreground">
          {{ data.trackingNumber }}
        </code>
      </div>

      <!-- Mismatch warning -->
      @if (data.mismatch) {
        <div class="flex items-start gap-2 text-xs p-2 rounded bg-warning/10 border border-warning/20">
          <sa-icon-alert class="w-3.5 h-3.5 text-warning mt-0.5 flex-shrink-0" />
          <span class="text-warning">
            Sandbox mismatch: requested
            <code class="font-mono">{{ data.requestedNumber }}</code>
            but UPS returned
            <code class="font-mono">{{ data.trackingNumber }}</code>
          </span>
        </div>
      }

      <!-- Activity section -->
      @if (activities.length > 0) {
        <div class="space-y-2">
          <!-- Activity toggle header -->
          <button
            (click)="toggleActivities()"
            class="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <span class="font-medium">Activity</span>
            <span class="text-[10px]">({{ activities.length }})</span>
            @if (canExpand) {
              <sa-icon-chevron-down
                class="w-3.5 h-3.5 transition-transform duration-200"
                [class.rotate-180]="isExpanded()"
              />
            }
          </button>

          <!-- Visual timeline -->
          <div class="relative">
            @for (act of visibleActivities(); track $index; let i = $index, last = $last) {
              <div class="relative flex gap-3 pb-4" [class.pb-0]="last">
                <!-- Connecting line -->
                @if (!last) {
                  <div class="absolute left-[7px] top-5 bottom-0 w-px bg-border"></div>
                }
                <!-- Timeline dot -->
                <div
                  class="relative z-10 mt-1 w-3.5 h-3.5 rounded-full border-2 flex-shrink-0"
                  [class.bg-[var(--color-domain-tracking)]]="i === 0"
                  [class.border-[var(--color-domain-tracking)]]="i === 0"
                  [class.bg-background]="i !== 0"
                  [class.border-border]="i !== 0"
                ></div>
                <!-- Content -->
                <div class="flex-1 min-w-0">
                  <p class="text-xs font-medium text-foreground">{{ act.status }}</p>
                  <p class="text-[10px] font-mono text-muted-foreground">
                    {{ formatDate(act.date) }} {{ formatTime(act.time) }}
                    @if (act.location) {
                      <span class="ml-1.5">· {{ act.location }}</span>
                    }
                  </p>
                </div>
              </div>
            }
          </div>

          <!-- Show more / less for activities -->
          @if (canExpand) {
            <button
              (click)="toggleActivities()"
              class="text-[11px] font-medium text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1"
            >
              {{ isExpanded() ? 'Show less' : 'Show all ' + activities.length + ' activities' }}
            </button>
          }
        </div>
      } @else {
        <p class="text-xs text-muted-foreground">No activity history available.</p>
      }
    </div>
  `,
})
export class TrackingCardComponent {
  @Input({ required: true }) data!: TrackingResult;

  readonly isExpanded = signal(false);

  get statusDisplay(): string {
    return this.data?.statusDescription || this.data?.currentStatus || '';
  }

  get statusInfo(): StatusInfo {
    return getStatusInfo(this.statusDisplay);
  }

  get isDelivered(): boolean {
    return this.statusInfo.label === 'DELIVERED';
  }

  get activities() {
    return this.data?.activities ?? [];
  }

  get canExpand(): boolean {
    return this.activities.length > COLLAPSED_ACTIVITY_COUNT;
  }

  readonly visibleActivities = computed(() => {
    const acts = this.data?.activities ?? [];
    if (this.isExpanded()) return acts;
    return acts.slice(0, COLLAPSED_ACTIVITY_COUNT);
  });

  toggleActivities(): void {
    if (this.canExpand) {
      this.isExpanded.update((v) => !v);
    }
  }

  protected formatDate = formatDateReadable;
  protected formatTime = formatActivityTime;
}
