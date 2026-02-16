/**
 * Inline card for pickup operation results in the chat thread.
 *
 * Renders 4 variants (scheduled, cancelled, rated, status) with
 * purple domain border. Accepts PickupResult as props.
 */

import { cn } from '@/lib/utils';
import type { PickupResult } from '@/types/api';
import { CheckIcon, XIcon } from '@/components/ui/icons';

const ACTION_META: Record<PickupResult['action'], { label: string; badge: string; badgeClass: string }> = {
  scheduled: { label: 'Pickup Scheduled', badge: 'SCHEDULED', badgeClass: 'badge-success' },
  cancelled: { label: 'Pickup Cancelled', badge: 'CANCELLED', badgeClass: 'badge-error' },
  rated: { label: 'Pickup Rate Estimate', badge: 'RATED', badgeClass: 'badge-info' },
  status: { label: 'Pickup Status', badge: 'STATUS', badgeClass: 'badge-neutral' },
};

export function PickupCard({ data }: { data: PickupResult }) {
  const meta = ACTION_META[data.action] ?? ACTION_META.status;

  return (
    <div className={cn('card-premium p-4 space-y-3 border-l-4 card-domain-pickup')}>
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-medium text-foreground">{meta.label}</h4>
        <span className={cn('badge', meta.badgeClass)}>{meta.badge}</span>
      </div>

      {/* Scheduled — show PRN */}
      {data.action === 'scheduled' && data.prn && (
        <div className="flex items-center gap-2 text-xs font-mono text-muted-foreground">
          <CheckIcon className="w-3.5 h-3.5 text-success" />
          <span>PRN: <span className="text-foreground">{data.prn}</span></span>
        </div>
      )}

      {/* Cancelled */}
      {data.action === 'cancelled' && (
        <div className="flex items-center gap-2 text-xs font-mono text-muted-foreground">
          <XIcon className="w-3.5 h-3.5 text-destructive" />
          <span>Pickup cancelled successfully</span>
        </div>
      )}

      {/* Rated — show charges */}
      {data.action === 'rated' && data.charges && data.charges.length > 0 && (
        <div className="space-y-1">
          {data.charges.map((c, i) => (
            <div key={i} className="flex items-center justify-between text-xs font-mono">
              <span className="text-muted-foreground">{c.chargeCode}</span>
              <span className="text-foreground">${c.chargeAmount}</span>
            </div>
          ))}
        </div>
      )}

      {/* Status — show pending pickups */}
      {data.action === 'status' && data.pickups && data.pickups.length > 0 && (
        <div className="space-y-1.5">
          {data.pickups.map((p, i) => (
            <div key={i} className="flex items-center justify-between text-xs font-mono px-2 py-1.5 rounded bg-muted">
              <span className="text-muted-foreground">PRN: {p.prn}</span>
              <span className="text-foreground">{p.pickupDate}</span>
            </div>
          ))}
        </div>
      )}

      {/* Status — no pending pickups */}
      {data.action === 'status' && (!data.pickups || data.pickups.length === 0) && (
        <p className="text-xs text-muted-foreground">No pending pickups found.</p>
      )}
    </div>
  );
}
