/**
 * Dashboard component for ShipAgent web interface.
 *
 * Industrial Logistics Terminal aesthetic - a precision instrument
 * for managing batch shipment operations.
 *
 * Manages the main workflow phases:
 * - input: Data source connection + Command entry with history
 * - preview: Preview grid before execution
 * - executing: Real-time progress display
 * - complete: Final summary and label downloads
 */

import * as React from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { CommandInput } from '@/components/CommandInput';
import { CommandHistory } from '@/components/CommandHistory';
import { PreviewGrid } from '@/components/PreviewGrid';
import { ConfirmationFooter } from '@/components/ConfirmationFooter';
import { ProgressDisplay } from '@/components/ProgressDisplay';
import { RowStatusTable } from '@/components/RowStatusTable';
import { ErrorAlert } from '@/components/ErrorAlert';
import { CompletionSummary } from '@/components/CompletionSummary';
import { LabelPreview } from '@/components/LabelPreview';
import { DataSourceManager } from '@/components/DataSourceManager';
import { useJobProgress } from '@/hooks/useJobProgress';
import {
  submitCommand,
  confirmJob,
  getJobPreview,
  getCommandHistory,
} from '@/lib/api';
import type {
  BatchPreview,
  CommandHistoryItem,
  DataSourceInfo,
  CsvImportConfig,
  ExcelImportConfig,
  DatabaseImportConfig,
} from '@/types/api';

/** Dashboard phase states. */
type DashboardPhase = 'input' | 'preview' | 'executing' | 'complete';

/**
 * Dashboard is the main application component.
 *
 * Workflow phases:
 * 1. input: Connect data source + User enters NL command or selects from history
 * 2. preview: Shows batch preview grid with confirmation footer
 * 3. executing: Real-time progress via SSE
 * 4. complete: Final summary with label downloads
 */
export function Dashboard() {
  // Phase state
  const [phase, setPhase] = React.useState<DashboardPhase>('input');

  // Data source state
  const [dataSource, setDataSource] = React.useState<DataSourceInfo | null>(null);

  // Command state
  const [commandHistory, setCommandHistory] = React.useState<CommandHistoryItem[]>([]);
  const [isHistoryLoading, setIsHistoryLoading] = React.useState(true);
  const [submitError, setSubmitError] = React.useState<string | null>(null);

  // Job state
  const [jobId, setJobId] = React.useState<string | null>(null);
  const [preview, setPreview] = React.useState<BatchPreview | null>(null);
  const [isPreviewLoading, setIsPreviewLoading] = React.useState(false);
  const [isConfirming, setIsConfirming] = React.useState(false);

  // Progress state from SSE hook
  const { progress, disconnect } = useJobProgress(
    phase === 'executing' ? jobId : null
  );

  // Error alert state
  const [showError, setShowError] = React.useState(true);

  // Row table expansion state
  const [rowTableExpanded, setRowTableExpanded] = React.useState(false);

  // Label preview modal state
  const [previewTrackingNumber, setPreviewTrackingNumber] = React.useState<string | null>(null);

  // Load command history on mount
  React.useEffect(() => {
    const loadHistory = async () => {
      try {
        const history = await getCommandHistory(10);
        setCommandHistory(history);
      } catch (err) {
        console.error('Failed to load command history:', err);
      } finally {
        setIsHistoryLoading(false);
      }
    };
    loadHistory();
  }, []);

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

  // Data source connection handler
  const handleDataSourceConnect = async (
    config: CsvImportConfig | ExcelImportConfig | DatabaseImportConfig
  ) => {
    // This would call the backend to connect the data source
    // For now, we'll simulate it since the backend API doesn't have
    // explicit data source endpoints yet (it's handled through the orchestrator)
    const mockDataSource: DataSourceInfo = {
      type: 'filePath' in config ? ('delimiter' in config ? 'csv' : 'excel') : 'database',
      status: 'connected',
      row_count: Math.floor(Math.random() * 5000) + 100,
      column_count: 12,
      columns: [
        { name: 'order_id', type: 'INTEGER', nullable: false, warnings: [] },
        { name: 'recipient_name', type: 'VARCHAR', nullable: false, warnings: [] },
        { name: 'address', type: 'VARCHAR', nullable: false, warnings: [] },
        { name: 'city', type: 'VARCHAR', nullable: false, warnings: [] },
        { name: 'state', type: 'VARCHAR', nullable: false, warnings: [] },
        { name: 'zip', type: 'VARCHAR', nullable: false, warnings: [] },
        { name: 'weight', type: 'DECIMAL', nullable: true, warnings: [] },
        { name: 'service', type: 'VARCHAR', nullable: true, warnings: [] },
      ],
      connected_at: new Date().toISOString(),
      ...(config as CsvImportConfig & ExcelImportConfig),
    };
    setDataSource(mockDataSource);
  };

  const handleDataSourceDisconnect = () => {
    setDataSource(null);
  };

  // Submit command handler
  const handleSubmit = async (command: string) => {
    setSubmitError(null);
    setIsPreviewLoading(true);

    try {
      const result = await submitCommand(command);
      setJobId(result.job_id);

      // Fetch preview
      const previewData = await getJobPreview(result.job_id);
      setPreview(previewData);
      setPhase('preview');

      // Refresh command history
      const history = await getCommandHistory(10);
      setCommandHistory(history);
    } catch (err) {
      setSubmitError(
        err instanceof Error ? err.message : 'Failed to submit command'
      );
    } finally {
      setIsPreviewLoading(false);
    }
  };

  // Select command from history
  const handleSelectHistory = (command: string) => {
    // Just populate - user will click submit
    handleSubmit(command);
  };

  // Confirm batch handler
  const handleConfirm = async () => {
    if (!jobId) return;

    setIsConfirming(true);
    try {
      await confirmJob(jobId);
      setPhase('executing');
      setRowTableExpanded(false);
      setShowError(true);
    } catch (err) {
      setSubmitError(
        err instanceof Error ? err.message : 'Failed to confirm batch'
      );
    } finally {
      setIsConfirming(false);
    }
  };

  // Start new batch handler
  const handleNewBatch = () => {
    setPhase('input');
    setJobId(null);
    setPreview(null);
    setSubmitError(null);
    setRowTableExpanded(false);
    setShowError(true);
    setIsPreviewLoading(false);
    setIsConfirming(false);
    setPreviewTrackingNumber(null);
  };

  // Open label preview modal
  const handlePreviewLabel = (trackingNumber: string) => {
    setPreviewTrackingNumber(trackingNumber);
  };

  // Close label preview modal
  const handleClosePreview = () => {
    setPreviewTrackingNumber(null);
  };

  // Cancel handler
  const handleCancel = () => {
    handleNewBatch();
  };

  return (
    <div className="min-h-screen bg-background pb-24">
      {/* Header - Industrial Terminal */}
      <header className="border-b border-border bg-gradient-to-r from-warehouse-900 to-warehouse-850">
        {/* Technical accent line */}
        <div className="h-[2px] bg-gradient-to-r from-transparent via-signal-500 to-transparent" />

        <div className="container mx-auto px-4 py-6">
          <div className="flex items-center justify-between">
            <div className="space-y-1">
              <div className="flex items-center gap-3">
                {/* Terminal icon */}
                <div className="relative">
                  <svg
                    className="h-8 w-8 text-signal-500"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <rect x="3" y="3" width="18" height="18" rx="2" strokeWidth={2} />
                    <path d="M9 9l2 2-2 2M15 15h-3" strokeWidth={2} strokeLinecap="round" />
                  </svg>
                  <div className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-status-go animate-pulse" />
                </div>
                <h1 className="font-display text-2xl font-bold tracking-tight text-foreground">
                  SHIPAGENT
                </h1>
              </div>
              <p className="font-mono-display text-xs text-muted-foreground tracking-wider uppercase">
                Natural Language Shipment Terminal
              </p>
            </div>

            {/* Status indicator */}
            <div className="flex items-center gap-4">
              {/* Data source status */}
              {dataSource && (
                <div className="flex items-center gap-2 px-3 py-1.5 rounded-sm bg-status-go/10 border border-status-go/30">
                  <div className="h-2 w-2 rounded-full bg-status-go animate-pulse" />
                  <span className="font-mono-display text-xs text-status-go">
                    {dataSource.type.toUpperCase()} CONNECTED
                  </span>
                </div>
              )}

              <div className="flex items-center gap-2 px-3 py-1.5 rounded-sm bg-warehouse-800 border border-steel-700">
                <div className={`h-2 w-2 rounded-full ${phase === 'executing' ? 'bg-status-go animate-pulse' : 'bg-steel-500'}`} />
                <span className="font-mono-display text-xs text-steel-300">
                  {phase === 'input' && 'READY'}
                  {phase === 'preview' && 'REVIEW'}
                  {phase === 'executing' && 'ACTIVE'}
                  {phase === 'complete' && 'DONE'}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Decorative barcode pattern */}
        <div className="h-1 barcode-pattern opacity-30" />
      </header>

      {/* Main content */}
      <main className="container mx-auto px-4 py-8 max-w-6xl">
        {/* Input Phase */}
        {phase === 'input' && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 animate-fade-in">
            {/* Left: Data Source Manager */}
            <div className="lg:col-span-1 space-y-6">
              <DataSourceManager
                dataSource={dataSource}
                onConnect={handleDataSourceConnect}
                onDisconnect={handleDataSourceDisconnect}
              />

              {/* Quick Tips */}
              <Card className="card-industrial">
                <CardHeader className="pb-2">
                  <CardTitle className="font-display text-sm">
                    Quick Tips
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  <div className="flex items-start gap-2">
                    <span className="font-mono-display text-xs text-signal-500">1.</span>
                    <p className="font-mono-display text-xs text-steel-400">
                      Connect your data source (CSV, Excel, or Database)
                    </p>
                  </div>
                  <div className="flex items-start gap-2">
                    <span className="font-mono-display text-xs text-signal-500">2.</span>
                    <p className="font-mono-display text-xs text-steel-400">
                      Enter a natural language command describing your shipment
                    </p>
                  </div>
                  <div className="flex items-start gap-2">
                    <span className="font-mono-display text-xs text-signal-500">3.</span>
                    <p className="font-mono-display text-xs text-steel-400">
                      Review the preview and confirm execution
                    </p>
                  </div>
                </CardContent>
              </Card>
            </div>

            {/* Right: Command Input */}
            <div className="lg:col-span-2 space-y-6">
              <Card className="card-industrial corner-accent">
                <CardHeader>
                  <div className="flex items-center gap-2">
                    <svg
                      className="h-5 w-5 text-signal-500"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path d="M12 5v14M5 12h14" strokeWidth={2} strokeLinecap="round" />
                    </svg>
                    <CardTitle className="font-display">Create Shipments</CardTitle>
                  </div>
                  <CardDescription className="font-mono-display text-xs">
                    {dataSource
                      ? `Connected to ${dataSource.type.toUpperCase()} with ${dataSource.row_count?.toLocaleString()} rows. Enter your shipment command below.`
                      : 'Connect a data source first, then enter a natural language command to process shipments.'
                    }
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <CommandInput
                    onSubmit={handleSubmit}
                    disabled={isPreviewLoading || !dataSource}
                  />

                  {/* Data source warning */}
                  {!dataSource && (
                    <div className="mt-4 p-3 rounded-sm bg-status-hold/10 border border-status-hold/30">
                      <p className="font-mono-display text-xs text-status-hold">
                        ⚠ Connect a data source to begin processing shipments
                      </p>
                    </div>
                  )}

                  {/* Submit error */}
                  {submitError && (
                    <div className="mt-4 p-3 rounded-sm bg-status-stop/10 border border-status-stop/30 animate-slide-up">
                      <p className="font-mono-display text-sm text-status-stop">
                        ERROR: {submitError}
                      </p>
                    </div>
                  )}
                </CardContent>
              </Card>

              {/* Command history */}
              <CommandHistory
                commands={commandHistory}
                onSelect={handleSelectHistory}
                isLoading={isHistoryLoading}
              />
            </div>
          </div>
        )}

        {/* Preview Phase */}
        {phase === 'preview' && (
          <div className="space-y-6 animate-scale-in">
            <Card className="card-industrial">
              <CardHeader>
                <div className="flex items-center gap-2">
                  <svg
                    className="h-5 w-5 text-route-500"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" strokeWidth={2} />
                    <path d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" strokeWidth={2} />
                  </svg>
                  <CardTitle className="font-display">Review Shipments</CardTitle>
                </div>
                <CardDescription className="font-mono-display text-xs">
                  Review the shipments below before confirming execution.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <PreviewGrid
                  preview={preview}
                  isLoading={isPreviewLoading}
                />
              </CardContent>
            </Card>

            {/* Submit error */}
            {submitError && (
              <Card className="border-status-stop/50 bg-status-stop/5 animate-slide-up">
                <CardContent className="pt-6">
                  <p className="font-mono-display text-sm text-status-stop">
                    ERROR: {submitError}
                  </p>
                </CardContent>
              </Card>
            )}
          </div>
        )}

        {/* Executing Phase */}
        {phase === 'executing' && jobId && (
          <div className="space-y-4 animate-fade-in">
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
            <div className="corner-accent">
              <ProgressDisplay jobId={jobId} />
            </div>

            {/* Row status table */}
            <RowStatusTable
              jobId={jobId}
              isExpanded={rowTableExpanded}
              onToggle={() => setRowTableExpanded(!rowTableExpanded)}
              autoRefresh={progress.status === 'running'}
              onPreviewLabel={handlePreviewLabel}
            />

            {/* Failed state actions */}
            {progress.status === 'failed' && (
              <div className="flex justify-center py-4">
                <Button onClick={handleNewBatch} className="btn-industrial font-mono-display">
                  Start New Batch
                </Button>
              </div>
            )}
          </div>
        )}

        {/* Complete Phase */}
        {phase === 'complete' && jobId && (
          <div className="space-y-4 animate-scale-in">
            {/* Completion summary with label downloads */}
            <CompletionSummary
              jobId={jobId}
              totalRows={progress.total}
              successfulRows={progress.successful}
              failedRows={progress.failed}
              totalCostCents={progress.totalCostCents}
              onNewBatch={handleNewBatch}
              onPreviewLabel={handlePreviewLabel}
            />

            {/* Row details for complete phase */}
            <RowStatusTable
              jobId={jobId}
              isExpanded={rowTableExpanded}
              onToggle={() => setRowTableExpanded(!rowTableExpanded)}
              autoRefresh={false}
              onPreviewLabel={handlePreviewLabel}
            />
          </div>
        )}
      </main>

      {/* Sticky Confirmation Footer - only in preview phase */}
      {phase === 'preview' && preview && (
        <ConfirmationFooter
          totalCost={preview.total_estimated_cost_cents}
          rowCount={preview.total_rows}
          onConfirm={handleConfirm}
          onCancel={handleCancel}
          isLoading={isConfirming}
          visible={true}
        />
      )}

      {/* Label Preview Modal */}
      {previewTrackingNumber && (
        <LabelPreview
          trackingNumber={previewTrackingNumber}
          isOpen={true}
          onClose={handleClosePreview}
        />
      )}
    </div>
  );
}

export default Dashboard;
