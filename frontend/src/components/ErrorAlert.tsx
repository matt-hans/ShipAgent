/**
 * ErrorAlert component for displaying batch execution errors.
 *
 * Shows an inline error banner with expandable details when a batch
 * fails during execution.
 */

import * as React from 'react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export interface ErrorAlertProps {
  /** The error code (e.g., "E-3001"). */
  errorCode: string;
  /** The error message. */
  errorMessage: string;
  /** The row number that failed (optional). */
  rowNumber?: number;
  /** Callback when the alert is dismissed. */
  onDismiss: () => void;
  /** Optional additional class name. */
  className?: string;
}

/**
 * AlertCircle icon component.
 */
function AlertCircleIcon({ className }: { className?: string }) {
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
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="8" x2="12" y2="12" />
      <line x1="12" y1="16" x2="12.01" y2="16" />
    </svg>
  );
}

/**
 * X icon for dismiss button.
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
 * Chevron icon for expand/collapse.
 */
function ChevronIcon({ isOpen, className }: { isOpen: boolean; className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={cn(
        'h-4 w-4 transition-transform duration-200',
        isOpen ? 'rotate-180' : '',
        className
      )}
    >
      <polyline points="6 9 12 15 18 9" />
    </svg>
  );
}

/**
 * ErrorAlert displays batch execution failures.
 *
 * Features:
 * - Inline alert banner (per CONTEXT.md Decision 2)
 * - Error code and summary message
 * - Expandable section with full details
 * - Row number indicator when applicable
 * - Dismiss button
 */
export function ErrorAlert({
  errorCode,
  errorMessage,
  rowNumber,
  onDismiss,
  className,
}: ErrorAlertProps) {
  const [isExpanded, setIsExpanded] = React.useState(false);

  // Parse error code category for context
  const getErrorCategory = (code: string): string => {
    if (code.startsWith('E-1')) return 'Data Error';
    if (code.startsWith('E-2')) return 'Validation Error';
    if (code.startsWith('E-3')) return 'UPS API Error';
    if (code.startsWith('E-4')) return 'System Error';
    if (code.startsWith('E-5')) return 'Authentication Error';
    return 'Error';
  };

  const errorCategory = getErrorCategory(errorCode);

  // Create a short summary for collapsed state
  const shortMessage =
    errorMessage.length > 80
      ? errorMessage.slice(0, 80) + '...'
      : errorMessage;

  return (
    <Alert
      variant="destructive"
      className={cn('relative', className)}
    >
      <AlertCircleIcon className="h-4 w-4" />

      <AlertTitle className="flex items-center gap-2 pr-8">
        <span className="font-mono text-sm">{errorCode}</span>
        <span className="text-muted-foreground">|</span>
        <span>{errorCategory}</span>
        {rowNumber !== undefined && (
          <>
            <span className="text-muted-foreground">|</span>
            <span className="text-sm">Row {rowNumber}</span>
          </>
        )}
      </AlertTitle>

      <AlertDescription className="mt-2">
        {/* Short message or full message based on expand state */}
        <p className="text-sm">
          {isExpanded ? errorMessage : shortMessage}
        </p>

        {/* Expand/collapse toggle if message is long */}
        {errorMessage.length > 80 && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setIsExpanded(!isExpanded)}
            className="mt-2 h-auto p-0 text-xs hover:bg-transparent"
          >
            <span>{isExpanded ? 'Show less' : 'Show more'}</span>
            <ChevronIcon isOpen={isExpanded} className="ml-1" />
          </Button>
        )}

        {/* Remediation suggestion if error code indicates recoverable error */}
        {isExpanded && (
          <div className="mt-3 text-xs text-muted-foreground border-t border-destructive/20 pt-3">
            <p className="font-medium mb-1">What you can do:</p>
            <ul className="list-disc list-inside space-y-1">
              {errorCode.startsWith('E-1') && (
                <li>Check your data source for missing or invalid values</li>
              )}
              {errorCode.startsWith('E-2') && (
                <li>Verify addresses and package details meet UPS requirements</li>
              )}
              {errorCode.startsWith('E-3') && (
                <li>The UPS service may be temporarily unavailable. Try again shortly.</li>
              )}
              {errorCode.startsWith('E-4') && (
                <li>This is a system issue. Please contact support if it persists.</li>
              )}
              {errorCode.startsWith('E-5') && (
                <li>Check your UPS credentials and authentication settings</li>
              )}
              <li>Correct the issue and re-run your command</li>
            </ul>
          </div>
        )}
      </AlertDescription>

      {/* Dismiss button */}
      <Button
        variant="ghost"
        size="icon"
        onClick={onDismiss}
        className="absolute top-2 right-2 h-6 w-6 hover:bg-destructive/20"
        aria-label="Dismiss error"
      >
        <XIcon className="h-4 w-4" />
      </Button>
    </Alert>
  );
}

export default ErrorAlert;
