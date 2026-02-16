/**
 * Preview card for pickup scheduling — shows all details + rate
 * with Confirm/Cancel buttons, mirroring InteractivePreviewCard.
 */

import type { PickupPreview } from '@/types/api';
import { CheckIcon, MapPinIcon, UserIcon } from '@/components/ui/icons';

/** Format YYYYMMDD to "Feb 17, 2026" style display. */
function formatPickupDate(raw: string): string {
  if (raw.length !== 8) return raw;
  const y = raw.slice(0, 4);
  const m = parseInt(raw.slice(4, 6), 10) - 1;
  const d = parseInt(raw.slice(6, 8), 10);
  const date = new Date(parseInt(y, 10), m, d);
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

/** Format HHMM to "9:00 AM" style display. */
function formatTime(raw: string): string {
  if (raw.length !== 4) return raw;
  const h = parseInt(raw.slice(0, 2), 10);
  const m = raw.slice(2, 4);
  const suffix = h >= 12 ? 'PM' : 'AM';
  const h12 = h === 0 ? 12 : h > 12 ? h - 12 : h;
  return `${h12}:${m} ${suffix}`;
}

interface PickupPreviewCardProps {
  data: PickupPreview;
  onConfirm: () => void;
  onCancel: () => void;
  isConfirming: boolean;
}

export function PickupPreviewCard({ data, onConfirm, onCancel, isConfirming }: PickupPreviewCardProps) {
  return (
    <div className="card-premium p-5 animate-scale-in max-w-lg border-l-4 card-domain-pickup">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-base font-semibold text-white">Pickup Preview</h3>
        <span className="badge badge-info">READY</span>
      </div>

      {/* Address + Contact grid */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div className="bg-slate-800/50 rounded-lg p-3">
          <div className="flex items-center gap-1.5 mb-2">
            <MapPinIcon className="w-3.5 h-3.5 text-slate-400" />
            <span className="text-[11px] font-medium text-slate-400 uppercase tracking-wider">Pickup Address</span>
          </div>
          <div className="space-y-0.5 text-sm text-slate-200">
            <p>{data.address_line}</p>
            <p className="text-slate-300">
              {data.city}, {data.state} {data.postal_code}
            </p>
            <p className="text-[10px] font-mono text-slate-500">{data.country_code}</p>
          </div>
        </div>

        <div className="bg-slate-800/50 rounded-lg p-3">
          <div className="flex items-center gap-1.5 mb-2">
            <UserIcon className="w-3.5 h-3.5 text-slate-400" />
            <span className="text-[11px] font-medium text-slate-400 uppercase tracking-wider">Contact</span>
          </div>
          <div className="space-y-0.5 text-sm text-slate-200">
            <p className="font-medium">{data.contact_name}</p>
            <p className="text-slate-400 text-xs font-mono">{data.phone_number}</p>
          </div>
        </div>
      </div>

      {/* Schedule row */}
      <div className="grid grid-cols-3 gap-3 mb-4">
        <div className="bg-slate-800/50 rounded-lg p-2.5 text-center">
          <p className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-1">Date</p>
          <p className="text-sm font-semibold text-white">{formatPickupDate(data.pickup_date)}</p>
        </div>
        <div className="bg-slate-800/50 rounded-lg p-2.5 text-center">
          <p className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-1">Ready</p>
          <p className="text-sm font-semibold text-white">{formatTime(data.ready_time)}</p>
        </div>
        <div className="bg-slate-800/50 rounded-lg p-2.5 text-center">
          <p className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-1">Close</p>
          <p className="text-sm font-semibold text-white">{formatTime(data.close_time)}</p>
        </div>
      </div>

      {/* Rate breakdown */}
      {data.charges && data.charges.length > 0 && (
        <div className="mb-4 rounded-lg border border-slate-700/50 overflow-hidden">
          <div className="px-3 py-2 bg-slate-800/30">
            <p className="text-[10px] font-medium text-slate-400 uppercase tracking-wider">Rate Breakdown</p>
          </div>
          <div className="divide-y divide-slate-800">
            {data.charges.map((c, i) => (
              <div key={i} className="flex items-center justify-between px-3 py-2 text-sm">
                <span className="text-slate-300">{c.chargeLabel}</span>
                <span className="font-mono text-slate-200">${c.chargeAmount}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Grand total */}
      <div className="bg-gradient-to-r from-purple-500/10 to-purple-500/5 border border-purple-500/20 rounded-lg p-3 mb-4 text-center">
        <p className="text-[10px] font-medium text-purple-400 uppercase tracking-wider mb-1">Estimated Cost</p>
        <p className="text-2xl font-bold text-purple-400">${data.grand_total}</p>
      </div>

      {/* Actions */}
      <div className="flex gap-3">
        <button
          onClick={onCancel}
          disabled={isConfirming}
          className="btn-secondary flex-1 h-9 text-sm"
        >
          Cancel
        </button>
        <button
          onClick={onConfirm}
          disabled={isConfirming}
          className="btn-primary flex-1 h-9 text-sm flex items-center justify-center gap-2"
        >
          {isConfirming ? (
            <>
              <span className="animate-spin h-3.5 w-3.5 border-2 border-white/20 border-t-white rounded-full" />
              <span>Scheduling...</span>
            </>
          ) : (
            <>
              <CheckIcon className="w-3.5 h-3.5" />
              <span>Confirm &amp; Schedule</span>
            </>
          )}
        </button>
      </div>
    </div>
  );
}
