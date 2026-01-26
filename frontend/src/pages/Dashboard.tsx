/**
 * Dashboard component for ShipAgent web interface.
 *
 * Manages the main application with two primary views:
 * - Shipments: Command entry, preview, execution, and completion
 * - Data Sources: External platform connection management
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
import { AppLayout, type AppTab } from '@/components/layout/AppLayout';
import { DataSourceManager } from '@/components/DataSourceManager';
import { useJobProgress } from '@/hooks/useJobProgress';
import {
  submitCommand,
  confirmJob,
  getJobPreview,
  getCommandHistory,
} from '@/lib/api';
import type { BatchPreview, CommandHistoryItem } from '@/types/api';

/** Shipment workflow phase states. */
type ShipmentPhase = 'input' | 'preview' | 'executing' | 'complete';

/**
 * ShipmentsView handles the shipment creation workflow.
 *
 * Phases:
 * 1. input: User enters NL command or selects from history
 * 2. preview: Shows batch preview grid with confirmation footer
 * 3. executing: Real-time progress via SSE
 * 4. complete: Final summary with label downloads
 */
function ShipmentsView() {
  // Phase state
  const [phase, setPhase] = React.useState<ShipmentPhase>('input');

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
    <>
      {/* Input Phase */}
      {phase === 'input' && (
        <div className="space-y-6 animate-reveal" style={{ animationFillMode: 'forwards' }}>
          <Card>
            <CardHeader>
              <CardTitle>Create Shipments</CardTitle>
              <CardDescription>
                Enter a natural language command to process shipments from your data source.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <CommandInput
                onSubmit={handleSubmit}
                disabled={isPreviewLoading}
              />

              {/* Submit error */}
              {submitError && (
                <p className="mt-4 text-sm text-destructive">
                  {submitError}
                </p>
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
      )}

      {/* Preview Phase */}
      {phase === 'preview' && (
        <div className="space-y-6 animate-reveal" style={{ animationFillMode: 'forwards' }}>
          <Card>
            <CardHeader>
              <CardTitle>Review Shipments</CardTitle>
              <CardDescription>
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
            <Card className="border-destructive/50">
              <CardContent className="pt-6">
                <p className="text-sm text-destructive">
                  {submitError}
                </p>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* Executing Phase */}
      {phase === 'executing' && jobId && (
        <div className="space-y-4 animate-reveal" style={{ animationFillMode: 'forwards' }}>
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
            onPreviewLabel={handlePreviewLabel}
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
        <div className="space-y-4 animate-reveal" style={{ animationFillMode: 'forwards' }}>
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
    </>
  );
}

/**
 * Dashboard is the main application component.
 *
 * Provides tab-based navigation between:
 * - Shipments: Create and manage batch shipments
 * - Data Sources: Connect to external platforms
 */
export function Dashboard() {
  const [activeTab, setActiveTab] = React.useState<AppTab>('shipments');

  return (
    <AppLayout activeTab={activeTab} onTabChange={setActiveTab}>
      {activeTab === 'shipments' && <ShipmentsView />}
      {activeTab === 'sources' && <DataSourceManager />}
    </AppLayout>
  );
}

export default Dashboard;
