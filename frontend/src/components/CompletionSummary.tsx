/**
 * CompletionSummary component for displaying batch completion results.
 *
 * Shows final statistics, download options for shipping labels,
 * and navigation to start a new batch.
 */

import * as React from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { LabelDownloadButton } from '@/components/LabelDownloadButton';
import { getJobRows } from '@/lib/api';
import { cn } from '@/lib/utils';
import type { JobRow } from '@/types/api';

export interface CompletionSummaryProps {
  /** The job ID. */
  jobId: string;
  /** Total rows in the batch. */
  totalRows: number;
  /** Number of successful rows. */
  successfulRows: number;
  /** Number of failed rows. */
  failedRows: number;
  /** Total cost in cents. */
  totalCostCents: number;
  /** Callback when "Start New Batch" is clicked. */
  onNewBatch: () => void;
  /** Callback to open label preview for a tracking number. */
  onPreviewLabel?: (trackingNumber: string) => void;
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
 * CompletionSummary displays batch completion results with download options.
 *
 * Features:
 * - Celebratory completion header with success icon
 * - Stats display: total, successful, failed, cost
 * - Bulk "Download All Labels" button (ZIP)
 * - Individual label list with preview/download buttons
 * - "Start New Batch" button to reset workflow
 * - Fetches job rows to show completed labels
 */
export function CompletionSummary({
  jobId,
  totalRows,
  successfulRows,
  failedRows,
  totalCostCents,
  onNewBatch,
  onPreviewLabel,
  className,
}: CompletionSummaryProps) {
  const [rows, setRows] = React.useState<JobRow[]>([]);
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  // Fetch completed rows with tracking numbers
  React.useEffect(() => {
    const fetchRows = async () => {
      try {
        const data = await getJobRows(jobId);
        // Filter to only show rows with tracking numbers
        const completedRows = data.filter(
          (row) => row.status === 'completed' && row.tracking_number
        );
        setRows(completedRows);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to fetch labels');
      } finally {
        setIsLoading(false);
      }
    };

    fetchRows();
  }, [jobId]);

  const handleDownloadAll = () => {
    // Trigger ZIP download via hidden anchor
    const link = document.createElement('a');
    link.href = `/api/v1/jobs/${jobId}/labels/zip`;
    link.download = `labels-${jobId}.zip`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <Card className={cn('w-full', className)}>
      {/* Celebratory header */}
      <CardHeader className="text-center pb-4">
        <div className="mx-auto mb-4 inline-flex items-center justify-center h-16 w-16 rounded-full bg-green-100 dark:bg-green-900/30">
          <CheckIcon className="h-8 w-8 text-green-600 dark:text-green-400" />
        </div>
        <CardTitle className="text-2xl">Batch Complete!</CardTitle>
        <CardDescription>
          {successfulRows === totalRows
            ? 'All shipments processed successfully'
            : `${successfulRows} of ${totalRows} shipments completed`}
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-6">
        {/* Stats grid */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-center">
          <StatCard
            value={totalRows}
            label="Total"
            variant="default"
          />
          <StatCard
            value={successfulRows}
            label="Successful"
            variant="success"
          />
          <StatCard
            value={failedRows}
            label="Failed"
            variant={failedRows > 0 ? 'error' : 'default'}
          />
          <StatCard
            value={formatCurrency(totalCostCents)}
            label="Total Cost"
            variant="default"
          />
        </div>

        {/* Download section */}
        <div className="border rounded-lg divide-y">
          {/* Bulk download header */}
          <div className="p-4 flex items-center justify-between">
            <div>
              <p className="font-medium">Download Labels</p>
              <p className="text-sm text-muted-foreground">
                {rows.length} label{rows.length !== 1 ? 's' : ''} available
              </p>
            </div>
            <Button
              variant="default"
              onClick={handleDownloadAll}
              disabled={rows.length === 0}
            >
              <DownloadIcon className="h-4 w-4 mr-2" />
              Download All (ZIP)
            </Button>
          </div>

          {/* Individual labels list */}
          {isLoading ? (
            <div className="p-4 text-center text-muted-foreground">
              Loading labels...
            </div>
          ) : error ? (
            <div className="p-4 text-center text-red-600 dark:text-red-400">
              {error}
            </div>
          ) : rows.length > 0 ? (
            <ScrollArea className="max-h-[200px]">
              <div className="divide-y">
                {rows.map((row) => (
                  <div
                    key={row.id}
                    className="p-3 flex items-center justify-between hover:bg-muted/50 transition-colors"
                  >
                    <div className="flex items-center gap-3">
                      <span className="text-xs text-muted-foreground font-mono">
                        #{row.row_number}
                      </span>
                      <span className="font-mono text-sm">
                        {row.tracking_number}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      {onPreviewLabel && row.tracking_number && (
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
                      {row.tracking_number && (
                        <LabelDownloadButton
                          trackingNumber={row.tracking_number}
                          variant="icon"
                        />
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </ScrollArea>
          ) : (
            <div className="p-4 text-center text-muted-foreground">
              No labels available
            </div>
          )}
        </div>
      </CardContent>

      <CardFooter className="flex justify-center border-t pt-4">
        <Button onClick={onNewBatch} size="lg">
          Start New Batch
        </Button>
      </CardFooter>
    </Card>
  );
}

// Stat card component
function StatCard({
  value,
  label,
  variant,
}: {
  value: number | string;
  label: string;
  variant: 'default' | 'success' | 'error';
}) {
  const bgStyles = {
    default: 'bg-muted',
    success: 'bg-green-50 dark:bg-green-900/20',
    error: 'bg-red-50 dark:bg-red-900/20',
  };

  const textStyles = {
    default: '',
    success: 'text-green-600 dark:text-green-400',
    error: 'text-red-600 dark:text-red-400',
  };

  return (
    <div className={cn('p-4 rounded-lg', bgStyles[variant])}>
      <p className={cn('text-2xl font-bold', textStyles[variant])}>
        {value}
      </p>
      <p className="text-sm text-muted-foreground">{label}</p>
    </div>
  );
}

// Inline SVG icons
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

function DownloadIcon({ className }: { className?: string }) {
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
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="7 10 12 15 17 10" />
      <line x1="12" y1="15" x2="12" y2="3" />
    </svg>
  );
}

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

export default CompletionSummary;
