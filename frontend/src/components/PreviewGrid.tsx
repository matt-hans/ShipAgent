/**
 * PreviewGrid component for displaying shipment preview cards.
 *
 * Shows a grid of shipment cards with recipient info, service type,
 * and cost estimates before batch execution.
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
      className={cn('h-4 w-4', className)}
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
      className={cn('h-5 w-5', className)}
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
      className={cn('h-4 w-4', className)}
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
 * Single shipment preview card.
 */
function PreviewCard({ row }: { row: PreviewRow }) {
  const hasWarnings = row.warnings.length > 0;

  return (
    <Card className={cn(
      'relative overflow-hidden transition-all duration-200',
      'hover:shadow-md hover:border-primary/30',
      hasWarnings && 'border-yellow-500/50'
    )}>
      {/* Row number badge */}
      <div className="absolute top-3 right-3 text-xs font-mono text-muted-foreground bg-muted/50 px-2 py-0.5 rounded">
        #{row.row_number}
      </div>

      <CardContent className="p-4 space-y-3">
        {/* Recipient info */}
        <div className="flex items-start gap-3">
          <div className="p-2 rounded-lg bg-primary/10 shrink-0">
            <PackageIcon className="text-primary" />
          </div>
          <div className="min-w-0">
            <h3 className="font-medium text-foreground truncate">
              {row.recipient_name}
            </h3>
            <p className="text-sm text-muted-foreground truncate">
              {row.city_state}
            </p>
          </div>
        </div>

        {/* Service and cost row */}
        <div className="flex items-center justify-between pt-2 border-t border-border/50">
          <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <TruckIcon />
            <span>{row.service}</span>
          </div>
          <span className="text-lg font-semibold text-foreground">
            {formatCurrency(row.estimated_cost_cents)}
          </span>
        </div>

        {/* Warnings */}
        {hasWarnings && (
          <div className="pt-2 border-t border-yellow-500/30">
            {row.warnings.map((warning, i) => (
              <div
                key={i}
                className="flex items-start gap-2 text-sm text-yellow-700 dark:text-yellow-400"
              >
                <WarningIcon className="shrink-0 mt-0.5" />
                <span>{warning}</span>
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
function PreviewCardSkeleton() {
  return (
    <Card className="overflow-hidden">
      <CardContent className="p-4 space-y-3">
        <div className="flex items-start gap-3">
          <div className="h-10 w-10 rounded-lg bg-muted animate-pulse" />
          <div className="flex-1 space-y-2">
            <div className="h-4 w-3/4 bg-muted rounded animate-pulse" />
            <div className="h-3 w-1/2 bg-muted rounded animate-pulse" />
          </div>
        </div>
        <div className="flex items-center justify-between pt-2 border-t border-border/50">
          <div className="h-4 w-24 bg-muted rounded animate-pulse" />
          <div className="h-6 w-16 bg-muted rounded animate-pulse" />
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
      <div className={cn('space-y-4', className)}>
        {/* Summary skeleton */}
        <div className="flex items-center justify-between">
          <div className="h-5 w-32 bg-muted rounded animate-pulse" />
          <div className="h-8 w-28 bg-muted rounded animate-pulse" />
        </div>
        {/* Grid skeleton */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <PreviewCardSkeleton key={i} />
          ))}
        </div>
      </div>
    );
  }

  if (!preview) {
    return (
      <div className={cn('text-center py-12', className)}>
        <PackageIcon className="h-12 w-12 mx-auto text-muted-foreground/50" />
        <p className="mt-3 text-muted-foreground">
          No preview available. Enter a command to see shipment details.
        </p>
      </div>
    );
  }

  const { preview_rows, total_rows, additional_rows, total_estimated_cost_cents, rows_with_warnings } = preview;

  return (
    <div className={cn('space-y-4', className)}>
      {/* Summary header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="space-y-1">
          <h2 className="text-lg font-semibold text-foreground">
            Shipment Preview
          </h2>
          <p className="text-sm text-muted-foreground">
            Showing {preview_rows.length} of {total_rows} shipment{total_rows !== 1 ? 's' : ''}
            {additional_rows > 0 && (
              <span className="ml-1">
                ({additional_rows} more not shown)
              </span>
            )}
            {rows_with_warnings > 0 && (
              <span className="ml-2 text-yellow-600 dark:text-yellow-400">
                <WarningIcon className="inline h-3.5 w-3.5 mr-1" />
                {rows_with_warnings} with warnings
              </span>
            )}
          </p>
        </div>
        <div className="text-right">
          <p className="text-xs text-muted-foreground uppercase tracking-wide">
            Estimated Total
          </p>
          <p className="text-2xl font-bold text-foreground">
            {formatCurrency(total_estimated_cost_cents)}
          </p>
        </div>
      </div>

      {/* Preview cards grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {preview_rows.map((row) => (
          <PreviewCard key={row.row_number} row={row} />
        ))}
      </div>

      {/* Additional rows indicator */}
      {additional_rows > 0 && (
        <div className="text-center py-4 border-t border-border/50">
          <p className="text-sm text-muted-foreground">
            <span className="font-medium">+{additional_rows}</span> additional shipment{additional_rows !== 1 ? 's' : ''} not shown in preview
          </p>
        </div>
      )}
    </div>
  );
}

export default PreviewGrid;
