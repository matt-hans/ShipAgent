/**
 * Dashboard component for ShipAgent web interface.
 *
 * Manages the main workflow phases:
 * - input: Command entry
 * - preview: Preview before execution (Plan 05)
 * - executing: Real-time progress display
 * - complete: Final summary and label downloads
 */

import * as React from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from '@/components/ui/card';
import { ProgressDisplay } from '@/components/ProgressDisplay';
import { RowStatusTable } from '@/components/RowStatusTable';
import { ErrorAlert } from '@/components/ErrorAlert';
import { useJobProgress } from '@/hooks/useJobProgress';
import { submitCommand, confirmJob, getJobPreview } from '@/lib/api';
import type { BatchPreview } from '@/types/api';

/** Dashboard phase states. */
type DashboardPhase = 'input' | 'preview' | 'executing' | 'complete';

/**
 * Formats cents as currency string.
 */
function formatCurrency(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

/**
 * Dashboard is the main application component.
 *
 * Workflow phases:
 * 1. input: User enters NL command
 * 2. preview: Shows batch preview with confirmation (Plan 05 will expand this)
 * 3. executing: Real-time progress via SSE
 * 4. complete: Final summary with label downloads
 */
export function Dashboard() {
  // Phase state
  const [phase, setPhase] = React.useState<DashboardPhase>('input');

  // Command input state
  const [command, setCommand] = React.useState('');
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [submitError, setSubmitError] = React.useState<string | null>(null);

  // Job state
  const [jobId, setJobId] = React.useState<string | null>(null);
  const [preview, setPreview] = React.useState<BatchPreview | null>(null);

  // Progress state from SSE hook
  const { progress, disconnect } = useJobProgress(
    phase === 'executing' ? jobId : null
  );

  // Error alert state
  const [showError, setShowError] = React.useState(true);

  // Row table expansion state
  const [rowTableExpanded, setRowTableExpanded] = React.useState(false);

  // Handle phase transitions based on progress events
  React.useEffect(() => {
    if (phase !== 'executing') return;

    if (progress.status === 'completed') {
      // Delay transition slightly for UX
      const timeout = setTimeout(() => {
        disconnect();
        setPhase('complete');
      }, 1000);
      return () => clearTimeout(timeout);
    }

    if (progress.status === 'failed') {
      setShowError(true);
    }
  }, [phase, progress.status, disconnect]);

  // Submit command handler
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!command.trim() || isSubmitting) return;

    setIsSubmitting(true);
    setSubmitError(null);

    try {
      const result = await submitCommand(command);
      setJobId(result.job_id);

      // Fetch preview
      const previewData = await getJobPreview(result.job_id);
      setPreview(previewData);
      setPhase('preview');
    } catch (err) {
      setSubmitError(
        err instanceof Error ? err.message : 'Failed to submit command'
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  // Confirm batch handler
  const handleConfirm = async () => {
    if (!jobId) return;

    try {
      await confirmJob(jobId);
      setPhase('executing');
      setRowTableExpanded(false);
      setShowError(true);
    } catch (err) {
      setSubmitError(
        err instanceof Error ? err.message : 'Failed to confirm batch'
      );
    }
  };

  // Start new batch handler
  const handleNewBatch = () => {
    setPhase('input');
    setCommand('');
    setJobId(null);
    setPreview(null);
    setSubmitError(null);
    setRowTableExpanded(false);
    setShowError(true);
  };

  // Cancel handler
  const handleCancel = () => {
    handleNewBatch();
  };

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b border-border bg-card">
        <div className="container mx-auto px-4 py-4">
          <h1 className="text-2xl font-bold text-foreground">ShipAgent</h1>
          <p className="text-sm text-muted-foreground">
            Natural language interface for batch shipment processing
          </p>
        </div>
      </header>

      {/* Main content */}
      <main className="container mx-auto px-4 py-8 max-w-4xl">
        {/* Input Phase */}
        {phase === 'input' && (
          <Card>
            <CardHeader>
              <CardTitle>Command Input</CardTitle>
              <CardDescription>
                Enter a natural language command to process shipments.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleSubmit}>
                <div className="flex gap-2">
                  <Input
                    value={command}
                    onChange={(e) => setCommand(e.target.value)}
                    placeholder="Ship all California orders using UPS Ground"
                    className="flex-1"
                    disabled={isSubmitting}
                  />
                  <Button type="submit" disabled={isSubmitting || !command.trim()}>
                    {isSubmitting ? 'Processing...' : 'Submit'}
                  </Button>
                </div>
              </form>

              {/* Submit error */}
              {submitError && (
                <p className="mt-3 text-sm text-red-600 dark:text-red-400">
                  {submitError}
                </p>
              )}

              {/* Example commands */}
              <div className="mt-6">
                <p className="text-sm text-muted-foreground mb-2">
                  Try an example:
                </p>
                <div className="flex flex-wrap gap-2">
                  {[
                    'Ship all orders from orders.csv using UPS Ground',
                    'Ship pending orders from California using UPS Next Day Air',
                    'Ship all items over 10 lbs using UPS Ground',
                  ].map((example) => (
                    <Button
                      key={example}
                      variant="outline"
                      size="sm"
                      onClick={() => setCommand(example)}
                      className="text-xs"
                    >
                      {example}
                    </Button>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Preview Phase - Basic implementation, Plan 05 will expand */}
        {phase === 'preview' && preview && (
          <div className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle>Batch Preview</CardTitle>
                <CardDescription>
                  Review shipments before processing
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  <div className="grid grid-cols-2 gap-4 text-sm">
                    <div>
                      <span className="text-muted-foreground">Total Shipments:</span>
                      <span className="ml-2 font-medium">{preview.total_rows}</span>
                    </div>
                    <div>
                      <span className="text-muted-foreground">Estimated Cost:</span>
                      <span className="ml-2 font-medium">
                        {formatCurrency(preview.total_estimated_cost_cents)}
                      </span>
                    </div>
                  </div>

                  {/* Preview rows summary */}
                  {preview.preview_rows.length > 0 && (
                    <div className="border rounded-lg p-3">
                      <p className="text-sm font-medium mb-2">Sample Shipments:</p>
                      <div className="space-y-2">
                        {preview.preview_rows.slice(0, 3).map((row) => (
                          <div
                            key={row.row_number}
                            className="text-sm flex justify-between"
                          >
                            <span>
                              Row {row.row_number}: {row.recipient_name} ({row.city_state})
                            </span>
                            <span className="font-mono">
                              {formatCurrency(row.estimated_cost_cents)}
                            </span>
                          </div>
                        ))}
                        {preview.additional_rows > 0 && (
                          <p className="text-xs text-muted-foreground">
                            +{preview.additional_rows} more shipments...
                          </p>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Warnings */}
                  {preview.rows_with_warnings > 0 && (
                    <p className="text-sm text-yellow-600 dark:text-yellow-400">
                      {preview.rows_with_warnings} row(s) have warnings
                    </p>
                  )}
                </div>
              </CardContent>
              <CardFooter className="flex justify-between border-t pt-4">
                <Button variant="outline" onClick={handleCancel}>
                  Cancel
                </Button>
                <Button onClick={handleConfirm}>
                  Confirm {preview.total_rows} Shipments ({formatCurrency(preview.total_estimated_cost_cents)})
                </Button>
              </CardFooter>
            </Card>
          </div>
        )}

        {/* Executing Phase */}
        {phase === 'executing' && jobId && (
          <div className="space-y-4">
            {/* Error alert */}
            {progress.error && showError && (
              <ErrorAlert
                errorCode={progress.error.code}
                errorMessage={progress.error.message}
                rowNumber={progress.processed}
                onDismiss={() => setShowError(false)}
              />
            )}

            {/* Progress display */}
            <ProgressDisplay jobId={jobId} />

            {/* Row status table */}
            <RowStatusTable
              jobId={jobId}
              isExpanded={rowTableExpanded}
              onToggle={() => setRowTableExpanded(!rowTableExpanded)}
              autoRefresh={progress.status === 'running'}
            />

            {/* Failed state actions */}
            {progress.status === 'failed' && (
              <div className="flex justify-center">
                <Button onClick={handleNewBatch}>Start New Batch</Button>
              </div>
            )}
          </div>
        )}

        {/* Complete Phase */}
        {phase === 'complete' && jobId && (
          <div className="space-y-4">
            <Card>
              <CardHeader className="text-center">
                <div className="mx-auto mb-4 inline-flex items-center justify-center h-16 w-16 rounded-full bg-green-100 dark:bg-green-900/30">
                  <CheckIcon className="h-8 w-8 text-green-600 dark:text-green-400" />
                </div>
                <CardTitle className="text-2xl">Batch Complete!</CardTitle>
                <CardDescription>
                  All shipments have been processed successfully
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-center">
                  <div className="p-4 rounded-lg bg-muted">
                    <p className="text-2xl font-bold">{progress.total}</p>
                    <p className="text-sm text-muted-foreground">Total</p>
                  </div>
                  <div className="p-4 rounded-lg bg-green-50 dark:bg-green-900/20">
                    <p className="text-2xl font-bold text-green-600 dark:text-green-400">
                      {progress.successful}
                    </p>
                    <p className="text-sm text-muted-foreground">Successful</p>
                  </div>
                  <div className="p-4 rounded-lg bg-red-50 dark:bg-red-900/20">
                    <p className="text-2xl font-bold text-red-600 dark:text-red-400">
                      {progress.failed}
                    </p>
                    <p className="text-sm text-muted-foreground">Failed</p>
                  </div>
                  <div className="p-4 rounded-lg bg-muted">
                    <p className="text-2xl font-bold">
                      {formatCurrency(progress.totalCostCents)}
                    </p>
                    <p className="text-sm text-muted-foreground">Total Cost</p>
                  </div>
                </div>

                {/* Label download section - prepared for Plan 05 */}
                <div className="mt-6 p-4 border rounded-lg">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="font-medium">Download Labels</p>
                      <p className="text-sm text-muted-foreground">
                        {progress.successful} label(s) available
                      </p>
                    </div>
                    <Button variant="outline" disabled>
                      <DownloadIcon className="h-4 w-4 mr-2" />
                      Download All (ZIP)
                    </Button>
                  </div>
                </div>
              </CardContent>
              <CardFooter className="flex justify-center border-t pt-4">
                <Button onClick={handleNewBatch} size="lg">
                  Start New Batch
                </Button>
              </CardFooter>
            </Card>

            {/* Row details for complete phase */}
            <RowStatusTable
              jobId={jobId}
              isExpanded={rowTableExpanded}
              onToggle={() => setRowTableExpanded(!rowTableExpanded)}
              autoRefresh={false}
            />
          </div>
        )}
      </main>
    </div>
  );
}

// Simple SVG icons
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

export default Dashboard;
