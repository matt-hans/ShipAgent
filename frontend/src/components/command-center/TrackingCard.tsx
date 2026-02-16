/**
 * Inline card for tracking results in the chat thread.
 *
 * Renders tracking status, activity timeline, and mismatch warnings
 * with blue domain border. Accepts TrackingResult as props.
 */

import { cn } from '@/lib/utils';
import type { TrackingResult } from '@/types/api';
import { SearchIcon, AlertIcon, CheckIcon } from '@/components/ui/icons';

/** Map status codes to badge styling. */
function getStatusBadge(status: string): { label: string; badgeClass: string } {
  const upper = (status || '').toUpperCase();
  if (upper.includes('DELIVER')) return { label: 'DELIVERED', badgeClass: 'badge-success' };
  if (upper.includes('TRANSIT') || upper.includes('IN TRANSIT')) return { label: 'IN TRANSIT', badgeClass: 'badge-info' };
  if (upper.includes('EXCEPTION') || upper.includes('ERROR')) return { label: 'EXCEPTION', badgeClass: 'badge-warning' };
  if (upper.includes('PICKUP') || upper.includes('PICKED UP')) return { label: 'PICKED UP', badgeClass: 'badge-info' };
  if (upper.includes('LABEL') || upper.includes('CREATED')) return { label: 'LABEL CREATED', badgeClass: 'badge-neutral' };
  return { label: status || 'UNKNOWN', badgeClass: 'badge-neutral' };
}

/** Format YYYYMMDD to readable date. */
function formatDate(date: string): string {
  if (!date || date.length !== 8) return date || '';
  return `${date.slice(4, 6)}/${date.slice(6, 8)}/${date.slice(0, 4)}`;
}

/** Format HHMMSS to readable time. */
function formatTime(time: string): string {
  if (!time || time.length < 4) return time || '';
  return `${time.slice(0, 2)}:${time.slice(2, 4)}`;
}

export function TrackingCard({ data }: { data: TrackingResult }) {
  const statusDisplay = data.statusDescription || data.currentStatus || '';
  const badge = getStatusBadge(statusDisplay);

  return (
    <div className={cn('card-premium p-4 space-y-3 border-l-4 card-domain-tracking')}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <SearchIcon className="w-4 h-4 text-[var(--color-domain-tracking)]" />
          <h4 className="text-sm font-medium text-foreground">Package Tracking</h4>
        </div>
        <span className={cn('badge', badge.badgeClass)}>{badge.label}</span>
      </div>

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

      {/* Current status */}
      {statusDisplay && (
        <div className="flex items-center gap-2 text-xs font-mono text-muted-foreground">
          <CheckIcon className="w-3.5 h-3.5 text-[var(--color-domain-tracking)]" />
          <span>Status: <span className="text-foreground">{statusDisplay}</span></span>
        </div>
      )}

      {/* Delivery date */}
      {data.deliveryDate && (
        <div className="text-xs text-muted-foreground">
          Delivery: <span className="text-foreground font-mono">{formatDate(data.deliveryDate)}</span>
        </div>
      )}

      {/* Activity timeline */}
      {data.activities && data.activities.length > 0 && (
        <div className="space-y-1">
          <span className="text-xs text-muted-foreground font-medium">Activity</span>
          <div className="max-h-48 overflow-y-auto scrollable space-y-1">
            {data.activities.map((act, i) => (
              <div
                key={i}
                className="flex items-start gap-3 text-xs font-mono px-2 py-1.5 rounded bg-muted"
              >
                <span className="text-muted-foreground whitespace-nowrap flex-shrink-0">
                  {formatDate(act.date)} {formatTime(act.time)}
                </span>
                <span className="text-foreground flex-1">{act.status}</span>
                {act.location && (
                  <span className="text-muted-foreground whitespace-nowrap">{act.location}</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* No activities */}
      {(!data.activities || data.activities.length === 0) && (
        <p className="text-xs text-muted-foreground">No activity history available.</p>
      )}
    </div>
  );
}
