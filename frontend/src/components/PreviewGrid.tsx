/**
 * PreviewGrid component for displaying shipment preview cards.
 *
 * Industrial Logistics Terminal aesthetic - shipping manifest inspired
 * grid layout with distinctive visual treatments.
 */

import { Card, CardContent } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import type { BatchPreview, PreviewRow } from '@/types/api';

export interface PreviewGridProps {
  /** The batch preview data. */
  preview: BatchPreview | null;
  /** Whether the preview is loading. */
  isLoading?: boolean;
  /** Optional additional class name. */
  className?: string;
}

/**
 * Formats cents as currency string.
 */
function formatCurrency(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

/**
 * Warning icon for shipments with warnings.
 */
function WarningIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  );
}

/**
 * Package icon for shipment cards.
 */
function PackageIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d="m16.5 9.4-9-5.19" />
      <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
      <polyline points="3.29 7 12 12 20.71 7" />
      <line x1="12" y1="22" x2="12" y2="12" />
    </svg>
  );
}

/**
 * Truck icon for service type.
 */
function TruckIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d="M14 18V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v11a1 1 0 0 0 1 1h2" />
      <path d="M15 18H9" />
      <path d="M19 18h2a1 1 0 0 0 1-1v-3.65a1 1 0 0 0-.22-.624l-3.48-4.35A1 1 0 0 0 17.52 8H14" />
      <circle cx="17" cy="18" r="2" />
      <circle cx="7" cy="18" r="2" />
    </svg>
  );
}

/**
 * Single shipment preview card with industrial styling.
 */
function PreviewCard({ row, index }: { row: PreviewRow; index: number }) {
  const hasWarnings = row.warnings.length > 0;

  return (
    <Card className={cn(
      'relative overflow-hidden transition-all duration-300',
      'bg-warehouse-900/50 border-steel-700 hover:border-signal-500/50',
      'hover:shadow-lg hover:shadow-signal-500/10',
      'animate-fade-in',
      `delay-${Math.min(index * 100, 500)}`,
      hasWarnings && 'border-status-hold/50'
    )}>
      {/* Technical corner markers */}
      <div className="absolute top-0 left-0 w-3 h-3 border-t-2 border-l-2 border-steel-600" />
      <div className="absolute top-0 right-0 w-3 h-3 border-t-2 border-r-2 border-steel-600" />
      <div className="absolute bottom-0 left-0 w-3 h-3 border-b-2 border-l-2 border-steel-600" />
      <div className="absolute bottom-0 right-0 w-3 h-3 border-b-2 border-r-2 border-steel-600" />

      {/* Row number badge */}
      <div className="absolute top-3 right-3 font-mono-display text-[10px] text-steel-400 bg-warehouse-800 px-2 py-1 rounded-sm border border-steel-700">
        #{String(row.row_number).padStart(3, '0')}
      </div>

      <CardContent className="p-4 space-y-3">
        {/* Recipient info */}
        <div className="flex items-start gap-3">
          <div className="p-2.5 rounded-sm bg-signal-500/10 border border-signal-500/30 shrink-0">
            <PackageIcon className="h-5 w-5 text-signal-500" />
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="font-display font-semibold text-steel-100 truncate">
              {row.recipient_name}
            </h3>
            <p className="font-mono-display text-xs text-steel-400 truncate">
              {row.city_state}
            </p>
          </div>
        </div>

        {/* Service and cost row */}
        <div className="flex items-center justify-between pt-3 border-t border-steel-700/50">
          <div className="flex items-center gap-2 text-xs text-steel-400">
            <TruckIcon className="h-4 w-4" />
            <span className="font-mono-display">{row.service}</span>
          </div>
          <span className="font-mono-display text-lg font-semibold text-signal-500">
            {formatCurrency(row.estimated_cost_cents)}
          </span>
        </div>

        {/* Warnings */}
        {hasWarnings && (
          <div className="pt-2 border-t border-status-hold/30">
            {row.warnings.map((warning, i) => (
              <div
                key={i}
                className="flex items-start gap-2 text-xs text-status-hold animate-slide-up"
                style={{ animationDelay: `${i * 50}ms` }}
              >
                <WarningIcon className="shrink-0 mt-0.5 h-3.5 w-3.5" />
                <span className="font-mono-display">{warning}</span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/**
 * Loading skeleton for preview cards.
 */
function PreviewCardSkeleton({ index: _index }: { index: number }) {
  return (
    <Card className="overflow-hidden bg-warehouse-900/50 border-steel-700 animate-pulse">
      <CardContent className="p-4 space-y-3">
        <div className="flex items-start gap-3">
          <div className="h-11 w-11 rounded-sm bg-steel-800" />
          <div className="flex-1 space-y-2">
            <div className="h-4 w-3/4 bg-steel-800 rounded" />
            <div className="h-3 w-1/2 bg-steel-800 rounded" />
          </div>
        </div>
        <div className="flex items-center justify-between pt-3 border-t border-steel-700/50">
          <div className="h-4 w-24 bg-steel-800 rounded" />
          <div className="h-6 w-16 bg-steel-800 rounded" />
        </div>
      </CardContent>
    </Card>
  );
}

/**
 * PreviewGrid displays shipment cards before batch execution.
 *
 * Features:
 * - Grid layout of shipment preview cards
 * - Recipient name and city/state
 * - Service type with icon
 * - Cost per shipment
 * - Warning badges for problematic shipments
 * - Summary showing total count and additional rows
 * - Total cost prominently displayed
 */
export function PreviewGrid({ preview, isLoading = false, className }: PreviewGridProps) {
  if (isLoading) {
    return (
      <div className={cn('space-y-6', className)}>
        {/* Summary skeleton */}
        <div className="flex items-center justify-between">
          <div className="space-y-2">
            <div className="h-6 w-40 bg-steel-800 rounded animate-pulse" />
            <div className="h-4 w-60 bg-steel-800 rounded animate-pulse" />
          </div>
          <div className="space-y-1 text-right">
            <div className="h-3 w-24 bg-steel-800 rounded animate-pulse ml-auto" />
            <div className="h-8 w-28 bg-steel-800 rounded animate-pulse ml-auto" />
          </div>
        </div>
        {/* Grid skeleton */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <PreviewCardSkeleton key={i} index={i} />
          ))}
        </div>
      </div>
    );
  }

  if (!preview) {
    return (
      <div className={cn('text-center py-16', className)}>
        <div className="inline-flex p-4 rounded-full bg-steel-800/50 mb-4">
          <PackageIcon className="h-12 w-12 text-steel-500" />
        </div>
        <p className="font-mono-display text-sm text-steel-400">
          [ NO PREVIEW DATA ]
        </p>
        <p className="mt-2 text-steel-500">
          Enter a command to see shipment details.
        </p>
      </div>
    );
  }

  const { preview_rows, total_rows, additional_rows, total_estimated_cost_cents, rows_with_warnings } = preview;

  return (
    <div className={cn('space-y-6', className)}>
      {/* Summary header */}
      <div className="flex flex-wrap items-center justify-between gap-4 p-4 rounded-sm bg-warehouse-800/50 border border-steel-700">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <h2 className="font-display text-lg font-semibold text-steel-100">
              SHIPMENT PREVIEW
            </h2>
            {rows_with_warnings > 0 && (
              <span className="badge-status hold">
                {rows_with_warnings} WARNINGS
              </span>
            )}
          </div>
          <p className="font-mono-display text-xs text-steel-400">
            DISPLAYING {preview_rows.length} OF {total_rows} SHIPMENT{total_rows !== 1 ? 'S' : ''}
            {additional_rows > 0 && (
              <span className="ml-2 text-status-hold">
                [+{additional_rows} HIDDEN]
              </span>
            )}
          </p>
        </div>
        <div className="text-right space-y-1">
          <p className="font-mono-display text-[10px] text-steel-500 uppercase tracking-widest">
            Estimated Total
          </p>
          <p className="font-mono-display text-2xl font-bold text-signal-500">
            {formatCurrency(total_estimated_cost_cents)}
          </p>
        </div>
      </div>

      {/* Preview cards grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {preview_rows.map((row, index) => (
          <PreviewCard key={row.row_number} row={row} index={index} />
        ))}
      </div>

      {/* Additional rows indicator */}
      {additional_rows > 0 && (
        <div className="text-center py-4 border-t border-steel-700/50 border-dashed">
          <p className="font-mono-display text-xs text-steel-500">
            [+{additional_rows} ADDITIONAL SHIPMENT{additional_rows !== 1 ? 'S' : ''} NOT SHOWN]
          </p>
        </div>
      )}
    </div>
  );
}

export default PreviewGrid;
