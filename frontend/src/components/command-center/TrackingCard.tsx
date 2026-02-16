/**
 * Inline card for tracking results in the chat thread.
 *
 * Renders a status hero section, tracking number, mismatch warnings,
 * and a visual activity timeline with dots and connecting lines.
 * Activities are collapsible (3 shown by default). Uses blue domain color.
 */

import * as React from 'react';
import { cn } from '@/lib/utils';
import type { TrackingResult } from '@/types/api';
import { SearchIcon, AlertIcon, CheckIcon, PackageIcon, ChevronDownIcon } from '@/components/ui/icons';

const COLLAPSED_ACTIVITY_COUNT = 3;

/** Status classification with hero section styling. */
interface StatusInfo {
  label: string;
  badgeClass: string;
  heroFrom: string;
  heroTo: string;
  heroBorder: string;
  HeroIcon: React.FC<{ className?: string }>;
  iconColor: string;
}

/** Map status text to badge class, hero gradient, and icon. */
function getStatusInfo(status: string): StatusInfo {
  const upper = (status || '').toUpperCase();

  if (upper.includes('DELIVER')) {
    return {
      label: 'DELIVERED',
      badgeClass: 'badge-success',
      heroFrom: 'from-success/10',
      heroTo: 'to-success/5',
      heroBorder: 'border-success/20',
      HeroIcon: CheckIcon,
      iconColor: 'text-success',
    };
  }
  if (upper.includes('EXCEPTION') || upper.includes('ERROR')) {
    return {
      label: 'EXCEPTION',
      badgeClass: 'badge-warning',
      heroFrom: 'from-warning/10',
      heroTo: 'to-warning/5',
      heroBorder: 'border-warning/20',
      HeroIcon: AlertIcon,
      iconColor: 'text-warning',
    };
  }
  if (upper.includes('TRANSIT') || upper.includes('IN TRANSIT')) {
    return {
      label: 'IN TRANSIT',
      badgeClass: 'badge-info',
      heroFrom: 'from-[var(--color-domain-tracking)]/10',
      heroTo: 'to-[var(--color-domain-tracking)]/5',
      heroBorder: 'border-[var(--color-domain-tracking)]/20',
      HeroIcon: PackageIcon,
      iconColor: 'text-[var(--color-domain-tracking)]',
    };
  }
  if (upper.includes('PICKUP') || upper.includes('PICKED UP')) {
    return {
      label: 'PICKED UP',
      badgeClass: 'badge-info',
      heroFrom: 'from-[var(--color-domain-tracking)]/10',
      heroTo: 'to-[var(--color-domain-tracking)]/5',
      heroBorder: 'border-[var(--color-domain-tracking)]/20',
      HeroIcon: PackageIcon,
      iconColor: 'text-[var(--color-domain-tracking)]',
    };
  }
  if (upper.includes('LABEL') || upper.includes('CREATED')) {
    return {
      label: 'LABEL CREATED',
      badgeClass: 'badge-neutral',
      heroFrom: 'from-[var(--color-domain-tracking)]/10',
      heroTo: 'to-[var(--color-domain-tracking)]/5',
      heroBorder: 'border-[var(--color-domain-tracking)]/20',
      HeroIcon: PackageIcon,
      iconColor: 'text-[var(--color-domain-tracking)]',
    };
  }
  return {
    label: status || 'UNKNOWN',
    badgeClass: 'badge-neutral',
    heroFrom: 'from-[var(--color-domain-tracking)]/10',
    heroTo: 'to-[var(--color-domain-tracking)]/5',
    heroBorder: 'border-[var(--color-domain-tracking)]/20',
    HeroIcon: PackageIcon,
    iconColor: 'text-[var(--color-domain-tracking)]',
  };
}

/** Format YYYYMMDD to readable "Mon DD, YYYY". */
function formatDateReadable(date: string): string {
  if (!date || date.length !== 8) return date || '';
  const d = new Date(+date.slice(0, 4), +date.slice(4, 6) - 1, +date.slice(6, 8));
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

/** Format HHMMSS to HH:MM. */
function formatTime(time: string): string {
  if (!time || time.length < 4) return time || '';
  return `${time.slice(0, 2)}:${time.slice(2, 4)}`;
}

export function TrackingCard({ data }: { data: TrackingResult }) {
  const [isActivityExpanded, setIsActivityExpanded] = React.useState(false);

  const statusDisplay = data.statusDescription || data.currentStatus || '';
  const info = getStatusInfo(statusDisplay);
  const isDelivered = info.label === 'DELIVERED';

  const activities = data.activities ?? [];
  const visibleActivities = isActivityExpanded
    ? activities
    : activities.slice(0, COLLAPSED_ACTIVITY_COUNT);
  const canExpandActivities = activities.length > COLLAPSED_ACTIVITY_COUNT;

  return (
    <div className={cn('card-premium p-4 space-y-3 border-l-4 card-domain-tracking')}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <SearchIcon className="w-4 h-4 text-[var(--color-domain-tracking)]" />
          <h4 className="text-sm font-medium text-foreground">Package Tracking</h4>
        </div>
        <span className={cn('badge', info.badgeClass)}>{info.label}</span>
      </div>

      {/* Status hero */}
      {statusDisplay && (
        <div className={cn(
          'rounded-lg p-3 bg-gradient-to-r border',
          info.heroFrom,
          info.heroTo,
          info.heroBorder
        )}>
          <div className="flex items-center gap-2.5">
            <info.HeroIcon className={cn('w-5 h-5', info.iconColor)} />
            <div>
              <p className="text-sm font-medium text-foreground">{statusDisplay}</p>
              {data.deliveryDate && (
                <p className="text-xs text-muted-foreground mt-0.5">
                  {isDelivered ? 'Delivered' : 'Expected'} {formatDateReadable(data.deliveryDate)}
                </p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Tracking number */}
      <div className="flex items-center gap-2 text-xs">
        <span className="text-muted-foreground">Tracking:</span>
        <code className="px-1.5 py-0.5 rounded bg-muted font-mono text-foreground">
          {data.trackingNumber}
        </code>
      </div>

      {/* Mismatch warning */}
      {data.mismatch && (
        <div className="flex items-start gap-2 text-xs p-2 rounded bg-warning/10 border border-warning/20">
          <AlertIcon className="w-3.5 h-3.5 text-warning mt-0.5 flex-shrink-0" />
          <span className="text-warning">
            Sandbox mismatch: requested <code className="font-mono">{data.requestedNumber}</code> but
            UPS returned <code className="font-mono">{data.trackingNumber}</code>
          </span>
        </div>
      )}

      {/* Activity section */}
      {activities.length > 0 ? (
        <div className="space-y-2">
          {/* Activity toggle header */}
          <button
            onClick={() => setIsActivityExpanded(!isActivityExpanded)}
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <span className="font-medium">Activity</span>
            <span className="text-[10px]">({activities.length})</span>
            {canExpandActivities && (
              <ChevronDownIcon className={cn(
                'w-3.5 h-3.5 transition-transform duration-200',
                isActivityExpanded && 'rotate-180'
              )} />
            )}
          </button>

          {/* Visual timeline */}
          <div className="relative">
            {visibleActivities.map((act, i) => (
              <div key={i} className="relative flex gap-3 pb-4 last:pb-0">
                {/* Connecting line */}
                {i < visibleActivities.length - 1 && (
                  <div className="absolute left-[7px] top-5 bottom-0 w-px bg-border" />
                )}
                {/* Timeline dot */}
                <div className={cn(
                  'relative z-10 mt-1 w-3.5 h-3.5 rounded-full border-2 flex-shrink-0',
                  i === 0
                    ? 'bg-[var(--color-domain-tracking)] border-[var(--color-domain-tracking)]'
                    : 'bg-background border-border'
                )} />
                {/* Content */}
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium text-foreground">{act.status}</p>
                  <p className="text-[10px] font-mono text-muted-foreground">
                    {formatDateReadable(act.date)} {formatTime(act.time)}
                    {act.location && <span className="ml-1.5">· {act.location}</span>}
                  </p>
                </div>
              </div>
            ))}
          </div>

          {/* Show more / less for activities */}
          {canExpandActivities && (
            <button
              onClick={() => setIsActivityExpanded(!isActivityExpanded)}
              className="text-[11px] font-medium text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1"
            >
              {isActivityExpanded
                ? 'Show less'
                : `Show all ${activities.length} activities`}
            </button>
          )}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">No activity history available.</p>
      )}
    </div>
  );
}
