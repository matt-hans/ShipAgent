/**
 * ConfirmationFooter component for batch confirmation.
 *
 * A sticky footer bar with confirm and cancel buttons that stays
 * visible while scrolling through the preview.
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
      className={cn('h-4 w-4', className)}
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
      className={cn('h-4 w-4', className)}
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
 * - Summary of shipment count and total cost
 * - Prominent confirm button with cost display
 * - Cancel button
 * - Loading state during confirmation
 * - Smooth slide-in/out animation
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
        'bg-card/95 backdrop-blur-sm',
        'border-t border-border shadow-lg',
        'transform transition-transform duration-300 ease-out',
        visible ? 'translate-y-0' : 'translate-y-full',
        className
      )}
    >
      <div className="container mx-auto px-4 py-4">
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
          {/* Summary section */}
          <div className="flex items-center gap-6">
            <div>
              <p className="text-sm text-muted-foreground">Shipments</p>
              <p className="text-xl font-bold text-foreground">{rowCount}</p>
            </div>
            <div className="h-10 w-px bg-border" />
            <div>
              <p className="text-sm text-muted-foreground">Estimated Total</p>
              <p className="text-xl font-bold text-foreground">
                {formatCurrency(totalCost)}
              </p>
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-3">
            <Button
              variant="outline"
              onClick={onCancel}
              disabled={isLoading}
              className="gap-2"
            >
              <XIcon />
              Cancel
            </Button>
            <Button
              onClick={onConfirm}
              disabled={isLoading}
              size="lg"
              className={cn(
                'gap-2 px-6',
                'bg-green-600 hover:bg-green-700',
                'text-white',
                'transition-all duration-200',
                !isLoading && 'hover:scale-[1.02] active:scale-[0.98]'
              )}
            >
              {isLoading ? (
                <>
                  <LoadingSpinner />
                  Confirming...
                </>
              ) : (
                <>
                  <CheckIcon />
                  Confirm {rowCount} Shipment{rowCount !== 1 ? 's' : ''} ({formatCurrency(totalCost)})
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
