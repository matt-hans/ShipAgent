/**
 * ConfirmationFooter component for batch confirmation.
 *
 * Industrial Terminal aesthetic - technical status bar style
 * confirmation footer with cost display and action buttons.
 */

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export interface ConfirmationFooterProps {
  /** Total cost in cents. */
  totalCost: number;
  /** Number of shipments in the batch. */
  rowCount: number;
  /** Callback when confirm is clicked. */
  onConfirm: () => void;
  /** Callback when cancel is clicked. */
  onCancel: () => void;
  /** Whether confirmation is in progress. */
  isLoading?: boolean;
  /** Whether the footer is visible. */
  visible?: boolean;
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
 * Check icon for confirm button.
 */
function CheckIcon({ className }: { className?: string }) {
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
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}

/**
 * X icon for cancel button.
 */
function XIcon({ className }: { className?: string }) {
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
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

/**
 * Loading spinner icon.
 */
function LoadingSpinner({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      className={cn('h-4 w-4 animate-spin', className)}
    >
      <path d="M21 12a9 9 0 1 1-6.219-8.56" />
    </svg>
  );
}

/**
 * ConfirmationFooter displays a sticky bar for batch confirmation.
 *
 * Features:
 * - Sticky positioning at bottom of viewport
 * - Technical status bar aesthetic with barcode pattern
 * - Summary of shipment count and total cost
 * - Prominent confirm button with cost display
 * - Cancel button with industrial styling
 * - Loading state during confirmation
 * - Smooth slide-in animation
 */
export function ConfirmationFooter({
  totalCost,
  rowCount,
  onConfirm,
  onCancel,
  isLoading = false,
  visible = true,
  className,
}: ConfirmationFooterProps) {
  if (!visible) {
    return null;
  }

  return (
    <div
      className={cn(
        'fixed bottom-0 left-0 right-0 z-50',
        'bg-gradient-to-r from-warehouse-900 via-warehouse-850 to-warehouse-900',
        'border-t border-steel-700 shadow-lg',
        'animate-slide-up',
        className
      )}
    >
      {/* Top accent line */}
      <div className="h-[1px] bg-gradient-to-r from-transparent via-signal-500 to-transparent" />

      {/* Barcode pattern */}
      <div className="h-1 barcode-pattern opacity-20" />

      <div className="container mx-auto px-4 py-4">
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
          {/* Summary section - Technical data display */}
          <div className="flex items-center gap-6">
            <div className="space-y-0.5">
              <p className="font-mono-display text-[10px] text-steel-500 uppercase tracking-widest">
                Batch Size
              </p>
              <div className="flex items-baseline gap-2">
                <p className="font-display text-2xl font-bold text-steel-100">
                  {rowCount}
                </p>
                <p className="font-mono-display text-sm text-steel-500">
                  SHIPMENT{rowCount !== 1 ? 'S' : ''}
                </p>
              </div>
            </div>

            <div className="hidden sm:block h-12 w-px bg-gradient-to-b from-transparent via-steel-700 to-transparent" />

            <div className="space-y-0.5">
              <p className="font-mono-display text-[10px] text-steel-500 uppercase tracking-widest">
                Estimated Cost
              </p>
              <div className="flex items-baseline gap-2">
                <p className="font-mono-display text-2xl font-bold text-signal-500">
                  {formatCurrency(totalCost)}
                </p>
              </div>
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-3">
            <Button
              variant="outline"
              onClick={onCancel}
              disabled={isLoading}
              className={cn(
                'font-mono-display text-sm uppercase tracking-wider',
                'border-steel-600 text-steel-300',
                'hover:bg-warehouse-800 hover:text-steel-100',
                'transition-all duration-200'
              )}
            >
              <XIcon className="h-4 w-4" />
              Cancel
            </Button>

            <Button
              onClick={onConfirm}
              disabled={isLoading}
              className={cn(
                'btn-industrial font-mono-display text-sm uppercase tracking-wider',
                'gap-2 px-6 py-5',
                'min-w-[240px]'
              )}
            >
              {isLoading ? (
                <>
                  <LoadingSpinner />
                  CONFIRMING...
                </>
              ) : (
                <>
                  <CheckIcon className="h-4 w-4" />
                  EXECUTE BATCH
                  <span className="text-signal-500/80">
                    ({formatCurrency(totalCost)})
                  </span>
                </>
              )}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default ConfirmationFooter;
