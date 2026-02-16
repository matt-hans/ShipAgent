/**
 * Unified card for pickup operation results in the chat thread.
 *
 * Renders 3 variants based on action:
 * - scheduled: rich completion artifact with PRN, address, contact, cost
 * - cancelled: cancellation confirmation
 * - status: pending pickups list
 *
 * Purple domain border via card-domain-pickup.
 */

import { cn } from '@/lib/utils';
import type { PickupResult } from '@/types/api';
import { CheckIcon, XIcon } from '@/components/ui/icons';

/** Format YYYYMMDD to "Feb 17, 2026" style display. */
function formatPickupDate(raw: string): string {
  if (!raw || raw.length !== 8) return raw || '';
  const y = raw.slice(0, 4);
  const m = parseInt(raw.slice(4, 6), 10) - 1;
  const d = parseInt(raw.slice(6, 8), 10);
  const date = new Date(parseInt(y, 10), m, d);
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

/** Format HHMM to "9:00 AM" style display. */
function formatTime(raw: string): string {
  if (!raw || raw.length !== 4) return raw || '';
  const h = parseInt(raw.slice(0, 2), 10);
  const m = raw.slice(2, 4);
  const suffix = h >= 12 ? 'PM' : 'AM';
  const h12 = h === 0 ? 12 : h > 12 ? h - 12 : h;
  return `${h12}:${m} ${suffix}`;
}

const ACTION_META: Record<string, { label: string; badge: string; badgeClass: string }> = {
  scheduled: { label: 'Pickup Scheduled', badge: 'CONFIRMED', badgeClass: 'badge-success' },
  cancelled: { label: 'Pickup Cancelled', badge: 'CANCELLED', badgeClass: 'badge-error' },
  status: { label: 'Pickup Status', badge: 'STATUS', badgeClass: 'badge-neutral' },
};

export function PickupCompletionCard({ data }: { data: PickupResult }) {
  const meta = ACTION_META[data.action] ?? ACTION_META.status;

  return (
    <div className="card-premium p-4 space-y-3 border-l-4 card-domain-pickup">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-medium text-foreground">{meta.label}</h4>
        <span className={cn('badge', meta.badgeClass)}>{meta.badge}</span>
      </div>

      {/* Scheduled — PRN + details */}
      {data.action === 'scheduled' && (
        <>
          {data.prn && (
            <div className="flex items-center gap-2 bg-slate-800/50 rounded-lg px-3 py-2">
              <CheckIcon className="w-4 h-4 text-success flex-shrink-0" />
              <span className="text-xs text-muted-foreground">PRN:</span>
              <span className="text-sm font-mono font-semibold text-foreground">{data.prn}</span>
            </div>
          )}

          {data.address_line && (
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-0.5">
                <p className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Address</p>
                <p className="text-xs text-slate-200">{data.address_line}</p>
                <p className="text-xs text-slate-300">
                  {data.city}, {data.state} {data.postal_code}
                </p>
              </div>
              <div className="space-y-0.5">
                <p className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Contact</p>
                <p className="text-xs text-slate-200">{data.contact_name}</p>
                <p className="text-xs text-slate-400 font-mono">{data.phone_number}</p>
              </div>
            </div>
          )}

          <div className="flex items-center gap-3 text-xs font-mono text-slate-400">
            {data.pickup_date && (
              <span>{formatPickupDate(data.pickup_date)}</span>
            )}
            {data.ready_time && data.close_time && (
              <>
                <span className="text-slate-600">&middot;</span>
                <span>{formatTime(data.ready_time)} – {formatTime(data.close_time)}</span>
              </>
            )}
            {data.grand_total && (
              <>
                <span className="text-slate-600">&middot;</span>
                <span className="text-purple-400">${data.grand_total}</span>
              </>
            )}
          </div>
        </>
      )}

      {/* Cancelled */}
      {data.action === 'cancelled' && (
        <div className="flex items-center gap-2 text-xs font-mono text-muted-foreground">
          <XIcon className="w-3.5 h-3.5 text-destructive" />
          <span>Pickup cancelled successfully</span>
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
