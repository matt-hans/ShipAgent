/**
 * RowStatusTable component for displaying per-row batch status.
 *
 * Shows a collapsible table with status, tracking number, cost, and
 * error information for each row in a batch job.
 */

import * as React from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { LabelDownloadButton } from '@/components/LabelDownloadButton';
import { getJobRows } from '@/lib/api';
import { cn } from '@/lib/utils';
import type { JobRow, RowStatus } from '@/types/api';

export interface RowStatusTableProps {
  /** The job ID to fetch rows for. */
  jobId: string;
  /** Whether the table is expanded. */
  isExpanded: boolean;
  /** Callback when expand/collapse is toggled. */
  onToggle: () => void;
  /** Whether to auto-refresh during execution. */
  autoRefresh?: boolean;
  /** Refresh interval in milliseconds. Default: 2000. */
  refreshInterval?: number;
  /** Callback to open label preview for a tracking number. */
  onPreviewLabel?: (trackingNumber: string) => void;
  /** Optional additional class name. */
  className?: string;
}

/**
 * Status badge component for row status.
 */
function StatusBadge({ status }: { status: RowStatus }) {
  const styles: Record<RowStatus, string> = {
    pending: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300',
    processing: 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300 animate-pulse',
    completed: 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300',
    failed: 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300',
    skipped: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-300',
  };

  return (
    <span
      className={cn(
        'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium',
        styles[status]
      )}
    >
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

/**
 * Formats cents as currency string.
 */
function formatCurrency(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

/**
 * Chevron icon component.
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
 * RowStatusTable displays per-row status for a batch job.
 *
 * Features:
 * - Collapsible table (collapsed by default per CONTEXT.md Decision 2)
 * - Status badge for each row
 * - Tracking number display for completed rows
 * - Cost display for completed rows
 * - Error message display for failed rows
 * - Auto-refresh during execution
 * - Scrollable content area for large batches
 */
export function RowStatusTable({
  jobId,
  isExpanded,
  onToggle,
  autoRefresh = false,
  refreshInterval = 2000,
  onPreviewLabel,
  className,
}: RowStatusTableProps) {
  const [rows, setRows] = React.useState<JobRow[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  // Fetch rows function
  const fetchRows = React.useCallback(async () => {
    if (!jobId) return;

    try {
      setLoading((prev) => rows.length === 0 ? true : prev);
      const data = await getJobRows(jobId);
      setRows(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch rows');
    } finally {
      setLoading(false);
    }
  }, [jobId, rows.length]);

  // Initial fetch when expanded
  React.useEffect(() => {
    if (isExpanded && rows.length === 0) {
      fetchRows();
    }
  }, [isExpanded, fetchRows, rows.length]);

  // Auto-refresh during execution
  React.useEffect(() => {
    if (!autoRefresh || !isExpanded) return;

    const interval = setInterval(fetchRows, refreshInterval);
    return () => clearInterval(interval);
  }, [autoRefresh, isExpanded, fetchRows, refreshInterval]);

  // Count rows by status
  const statusCounts = React.useMemo(() => {
    const counts = {
      pending: 0,
      processing: 0,
      completed: 0,
      failed: 0,
      skipped: 0,
    };
    rows.forEach((row) => {
      if (row.status in counts) {
        counts[row.status as keyof typeof counts]++;
      }
    });
    return counts;
  }, [rows]);

  return (
    <Card className={cn('w-full', className)}>
      <CardHeader className="pb-2">
        <Button
          variant="ghost"
          onClick={onToggle}
          className="w-full flex items-center justify-between p-0 h-auto hover:bg-transparent"
        >
          <CardTitle className="text-base font-medium">
            Row Details
          </CardTitle>
          <div className="flex items-center gap-3">
            {/* Quick status counts when collapsed */}
            {!isExpanded && rows.length > 0 && (
              <div className="flex gap-2 text-xs">
                {statusCounts.completed > 0 && (
                  <span className="text-green-600 dark:text-green-400">
                    {statusCounts.completed} done
                  </span>
                )}
                {statusCounts.pending > 0 && (
                  <span className="text-gray-500">
                    {statusCounts.pending} pending
                  </span>
                )}
                {statusCounts.failed > 0 && (
                  <span className="text-red-600 dark:text-red-400">
                    {statusCounts.failed} failed
                  </span>
                )}
              </div>
            )}
            <span className="text-sm text-muted-foreground">
              {isExpanded ? 'Hide details' : 'Show details'}
            </span>
            <ChevronIcon isOpen={isExpanded} />
          </div>
        </Button>
      </CardHeader>

      {isExpanded && (
        <CardContent>
          {loading && rows.length === 0 ? (
            <div className="flex items-center justify-center py-8">
              <p className="text-muted-foreground">Loading rows...</p>
            </div>
          ) : error ? (
            <div className="flex items-center justify-center py-8">
              <p className="text-red-600 dark:text-red-400">{error}</p>
            </div>
          ) : rows.length === 0 ? (
            <div className="flex items-center justify-center py-8">
              <p className="text-muted-foreground">No rows to display</p>
            </div>
          ) : (
            <ScrollArea className="h-[300px]">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-card border-b">
                  <tr className="text-left text-muted-foreground">
                    <th className="py-2 px-2 font-medium w-16">#</th>
                    <th className="py-2 px-2 font-medium w-28">Status</th>
                    <th className="py-2 px-2 font-medium">Tracking</th>
                    <th className="py-2 px-2 font-medium w-20 text-right">Cost</th>
                    <th className="py-2 px-2 font-medium">Error</th>
                    <th className="py-2 px-2 font-medium w-24 text-center">Label</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {rows.map((row) => (
                    <tr
                      key={row.id}
                      className={cn(
                        'hover:bg-muted/50 transition-colors',
                        row.status === 'failed' && 'bg-red-50 dark:bg-red-900/10'
                      )}
                    >
                      <td className="py-2 px-2 font-mono text-muted-foreground">
                        {row.row_number}
                      </td>
                      <td className="py-2 px-2">
                        <StatusBadge status={row.status} />
                      </td>
                      <td className="py-2 px-2 font-mono text-xs">
                        {row.tracking_number || (
                          <span className="text-muted-foreground">-</span>
                        )}
                      </td>
                      <td className="py-2 px-2 text-right font-mono">
                        {row.cost_cents != null ? (
                          formatCurrency(row.cost_cents)
                        ) : (
                          <span className="text-muted-foreground">-</span>
                        )}
                      </td>
                      <td className="py-2 px-2">
                        {row.error_message ? (
                          <span className="text-red-600 dark:text-red-400 text-xs">
                            {row.error_code}: {row.error_message}
                          </span>
                        ) : (
                          <span className="text-muted-foreground">-</span>
                        )}
                      </td>
                      <td className="py-2 px-2 text-center">
                        {row.tracking_number && row.status === 'completed' ? (
                          <div className="flex items-center justify-center gap-1">
                            {onPreviewLabel && (
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-8 w-8 p-0"
                                onClick={() => onPreviewLabel(row.tracking_number!)}
                                title="Preview label"
                              >
                                <EyeIcon className="h-4 w-4" />
                                <span className="sr-only">Preview</span>
                              </Button>
                            )}
                            <LabelDownloadButton
                              trackingNumber={row.tracking_number}
                              variant="icon"
                            />
                          </div>
                        ) : (
                          <span className="text-muted-foreground">-</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </ScrollArea>
          )}
        </CardContent>
      )}
    </Card>
  );
}

// Eye icon for preview button
function EyeIcon({ className }: { className?: string }) {
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
      <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

export default RowStatusTable;
