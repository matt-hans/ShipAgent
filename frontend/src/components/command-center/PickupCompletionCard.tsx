/**
 * Completion artifact for a scheduled pickup — shows PRN, address, time,
 * contact, and cost. Mirrors CompletionArtifact for shipping.
 */

import { cn } from '@/lib/utils';
import type { PickupResult } from '@/types/api';
import { CheckIcon } from '@/components/ui/icons';

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

export function PickupCompletionCard({ data }: { data: PickupResult }) {
  return (
    <div className="card-premium p-4 space-y-3 border-l-4 card-domain-pickup">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-medium text-foreground">Pickup Scheduled</h4>
        <span className={cn('badge', 'badge-success')}>CONFIRMED</span>
      </div>

      {/* PRN */}
      {data.prn && (
        <div className="flex items-center gap-2 bg-slate-800/50 rounded-lg px-3 py-2">
          <CheckIcon className="w-4 h-4 text-success flex-shrink-0" />
          <span className="text-xs text-muted-foreground">PRN:</span>
          <span className="text-sm font-mono font-semibold text-foreground">{data.prn}</span>
        </div>
      )}

      {/* Details grid */}
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

      {/* Schedule + cost */}
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
    </div>
  );
}
