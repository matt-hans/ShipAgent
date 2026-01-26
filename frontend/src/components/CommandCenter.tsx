/**
 * CommandCenter - Conversational interface for issuing shipping commands.
 *
 * Features:
 * - Chat-style conversation thread
 * - Command input with autocomplete
 * - Preview cards inline in conversation
 * - Progress display during execution
 * - Elicitation for clarifying questions
 */

import * as React from 'react';
import { useAppState, type ConversationMessage } from '@/hooks/useAppState';
import { useJobProgress } from '@/hooks/useJobProgress';
import { cn } from '@/lib/utils';
import { submitCommand, getJobPreview, confirmJob, cancelJob, getJob } from '@/lib/api';
import type { Job, BatchPreview } from '@/types/api';

interface CommandCenterProps {
  activeJob: Job | null;
}

// Icons
function SendIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={className}>
      <path d="M22 2L11 13" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M22 2L15 22L11 13L2 9L22 2Z" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function StopIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={className}>
      <rect x="6" y="6" width="12" height="12" rx="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function CheckIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={className}>
      <polyline points="20 6 9 17 4 12" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function XIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={className}>
      <line x1="18" y1="6" x2="6" y2="18" strokeLinecap="round" strokeLinejoin="round" />
      <line x1="6" y1="6" x2="18" y2="18" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function DownloadIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={className}>
      <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" strokeLinecap="round" strokeLinejoin="round" />
      <polyline points="7 10 12 15 17 10" strokeLinecap="round" strokeLinejoin="round" />
      <line x1="12" y1="15" x2="12" y2="3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function PackageIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className={className}>
      <path d="M16.5 9.4l-9-5.19" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z" strokeLinecap="round" strokeLinejoin="round" />
      <polyline points="3.27 6.96 12 12.01 20.73 6.96" strokeLinecap="round" strokeLinejoin="round" />
      <line x1="12" y1="22.08" x2="12" y2="12" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// Format currency from cents
function formatCurrency(cents: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
  }).format(cents / 100);
}

// Format relative time
function formatRelativeTime(date: Date): string {
  const diff = Date.now() - date.getTime();
  const minutes = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);

  if (hours > 0) return `${hours}h ago`;
  if (minutes > 0) return `${minutes}m ago`;
  return 'Just now';
}

// Message components
function SystemMessage({ message }: { message: ConversationMessage }) {
  return (
    <div className="flex gap-3 animate-fade-in-up">
      {/* Avatar */}
      <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500/20 to-cyan-600/20 border border-cyan-500/30 flex items-center justify-center">
        <PackageIcon className="w-4 h-4 text-cyan-400" />
      </div>

      <div className="flex-1 space-y-2">
        <div className="message-system">
          <p className="text-sm text-slate-200 whitespace-pre-wrap">{message.content}</p>
        </div>

        <span className="text-[10px] font-mono text-slate-500">
          {formatRelativeTime(message.timestamp)}
        </span>
      </div>
    </div>
  );
}

function UserMessage({ message }: { message: ConversationMessage }) {
  return (
    <div className="flex gap-3 justify-end animate-fade-in-up">
      <div className="flex-1 space-y-2 flex flex-col items-end">
        <div className="message-user">
          <p className="text-sm whitespace-pre-wrap">{message.content}</p>
        </div>

        <span className="text-[10px] font-mono text-slate-500">
          {formatRelativeTime(message.timestamp)}
        </span>
      </div>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="flex gap-3 animate-fade-in">
      <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500/20 to-cyan-600/20 border border-cyan-500/30 flex items-center justify-center">
        <PackageIcon className="w-4 h-4 text-cyan-400" />
      </div>

      <div className="message-system py-3">
        <div className="typing-indicator">
          <span />
          <span />
          <span />
        </div>
      </div>
    </div>
  );
}

// Preview card component
function PreviewCard({
  preview,
  onConfirm,
  onCancel,
  isConfirming,
}: {
  preview: BatchPreview;
  onConfirm: () => void;
  onCancel: () => void;
  isConfirming: boolean;
}) {
  return (
    <div className="card-premium p-4 space-y-4 animate-scale-in border-gradient">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-slate-200">Shipment Preview</h3>
        <span className="badge badge-info">Ready</span>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-3">
        <div className="p-3 rounded-lg bg-slate-800/50 text-center">
          <p className="text-2xl font-semibold text-slate-100">{preview.total_rows}</p>
          <p className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Total Rows</p>
        </div>
        <div className="p-3 rounded-lg bg-slate-800/50 text-center">
          <p className="text-2xl font-semibold text-amber-400">
            {formatCurrency(preview.total_estimated_cost_cents)}
          </p>
          <p className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Est. Cost</p>
        </div>
        <div className="p-3 rounded-lg bg-slate-800/50 text-center">
          <p className="text-2xl font-semibold text-slate-100">{preview.rows_with_warnings}</p>
          <p className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Warnings</p>
        </div>
      </div>

      {/* Sample rows */}
      {preview.preview_rows.length > 0 && (
        <div className="space-y-2">
          <p className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Sample Shipments</p>
          <div className="max-h-40 overflow-y-auto rounded-md border border-slate-800">
            {preview.preview_rows.slice(0, 5).map((row, i) => (
              <div
                key={i}
                className="flex items-center justify-between px-3 py-2 border-b border-slate-800 last:border-0 text-xs"
              >
                <div className="flex-1">
                  <span className="text-slate-300">{row.recipient_name}</span>
                  <span className="text-slate-500 ml-2">{row.city_state}</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="font-mono text-slate-400">{row.service}</span>
                  <span className="font-mono text-amber-400">{formatCurrency(row.estimated_cost_cents)}</span>
                </div>
              </div>
            ))}
          </div>
          {preview.additional_rows > 0 && (
            <p className="text-[10px] text-center text-slate-500">
              +{preview.additional_rows} more rows
            </p>
          )}
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-3 pt-2">
        <button
          onClick={onCancel}
          disabled={isConfirming}
          className="flex-1 btn-secondary py-2.5 flex items-center justify-center gap-2"
        >
          <XIcon className="w-4 h-4" />
          <span>Cancel</span>
        </button>
        <button
          onClick={onConfirm}
          disabled={isConfirming}
          className="flex-1 btn-primary py-2.5 flex items-center justify-center gap-2"
        >
          {isConfirming ? (
            <>
              <span className="w-4 h-4 border-2 border-void-950/30 border-t-void-950 rounded-full animate-spin" />
              <span>Confirming...</span>
            </>
          ) : (
            <>
              <CheckIcon className="w-4 h-4" />
              <span>Confirm & Execute</span>
            </>
          )}
        </button>
      </div>
    </div>
  );
}

// Progress display component
function ProgressDisplay({ jobId }: { jobId: string }) {
  const { progress } = useJobProgress(jobId);

  const percentage = progress.total > 0 ? Math.round((progress.processed / progress.total) * 100) : 0;
  const isRunning = progress.status === 'running';
  const isComplete = progress.status === 'completed';
  const isFailed = progress.status === 'failed';

  return (
    <div className={cn(
      'card-premium p-4 space-y-4',
      isRunning && 'scan-line',
      isComplete && 'border-success/30',
      isFailed && 'border-error/30'
    )}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-slate-200">
          {isComplete ? 'Batch Complete' : isFailed ? 'Batch Failed' : 'Processing Shipments'}
        </h3>
        <span className={cn(
          'badge',
          isComplete && 'badge-success',
          isFailed && 'badge-error',
          isRunning && 'badge-info'
        )}>
          {progress.status}
        </span>
      </div>

      {/* Progress bar */}
      <div className="space-y-2">
        <div className="progress-bar">
          <div
            className={cn('progress-bar-fill', isRunning && 'animated')}
            style={{ width: `${percentage}%` }}
          />
        </div>
        <div className="flex justify-between text-xs font-mono">
          <span className="text-slate-400">
            {progress.processed} / {progress.total} rows
          </span>
          <span className="text-slate-400">{percentage}%</span>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-4 gap-2">
        <div className="p-2 rounded bg-slate-800/50 text-center">
          <p className="text-lg font-semibold text-slate-100">{progress.total}</p>
          <p className="text-[10px] font-mono text-slate-500">Total</p>
        </div>
        <div className="p-2 rounded bg-slate-800/50 text-center">
          <p className="text-lg font-semibold text-success">{progress.successful}</p>
          <p className="text-[10px] font-mono text-slate-500">Success</p>
        </div>
        <div className="p-2 rounded bg-slate-800/50 text-center">
          <p className="text-lg font-semibold text-error">{progress.failed}</p>
          <p className="text-[10px] font-mono text-slate-500">Failed</p>
        </div>
        <div className="p-2 rounded bg-slate-800/50 text-center">
          <p className="text-lg font-semibold text-amber-400">
            {formatCurrency(progress.totalCostCents)}
          </p>
          <p className="text-[10px] font-mono text-slate-500">Cost</p>
        </div>
      </div>

      {/* Error message if failed */}
      {isFailed && progress.error && (
        <div className="p-3 rounded-lg bg-error/10 border border-error/30">
          <p className="text-xs font-mono text-error">
            {progress.error.code}: {progress.error.message}
          </p>
        </div>
      )}

      {/* Download button if complete */}
      {isComplete && (
        <button className="w-full btn-primary py-2.5 flex items-center justify-center gap-2">
          <DownloadIcon className="w-4 h-4" />
          <span>Download All Labels (ZIP)</span>
        </button>
      )}
    </div>
  );
}

// Welcome message with workflow steps
function WelcomeMessage({ onExampleClick }: { onExampleClick?: (text: string) => void }) {
  const { dataSource } = useAppState();

  const examples = [
    { text: 'Ship all California orders using UPS Ground', desc: 'Filter by state' },
    { text: "Ship today's pending orders with 2nd Day Air", desc: 'Filter by status & date' },
    { text: 'Create shipments for orders over $100', desc: 'Filter by amount' },
  ];

  // Not connected - show getting started workflow
  if (!dataSource) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center px-4 animate-fade-in">
        <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-amber-500/20 to-amber-600/20 border border-amber-500/30 flex items-center justify-center mb-6">
          <PackageIcon className="w-8 h-8 text-amber-400" />
        </div>

        <h2 className="text-xl font-semibold text-slate-100 mb-2">
          Welcome to ShipAgent
        </h2>

        <p className="text-sm text-slate-400 max-w-md mb-8">
          Natural language batch shipment processing powered by AI.
          <br />
          Connect a data source from the sidebar to get started.
        </p>

        {/* Workflow steps */}
        <div className="grid grid-cols-3 gap-4 w-full max-w-lg mb-8">
          {[
            { step: '1', title: 'Connect', desc: 'CSV, Excel, or Database' },
            { step: '2', title: 'Describe', desc: 'Natural language command' },
            { step: '3', title: 'Ship', desc: 'Preview, approve, execute' },
          ].map((item) => (
            <div key={item.step} className="text-center">
              <div className="w-8 h-8 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center mx-auto mb-2">
                <span className="text-xs font-mono text-amber-400">{item.step}</span>
              </div>
              <p className="text-xs font-medium text-slate-200">{item.title}</p>
              <p className="text-[10px] text-slate-500">{item.desc}</p>
            </div>
          ))}
        </div>

        {/* Example commands (preview) */}
        <div className="space-y-2 w-full max-w-md opacity-50">
          <p className="text-[10px] font-mono text-slate-600 uppercase tracking-wider">Example commands</p>
          <div className="space-y-1.5">
            {examples.map((example, i) => (
              <div
                key={i}
                className="px-3 py-2 rounded-lg bg-slate-800/30 border border-slate-800/50 text-left"
              >
                <p className="text-xs text-slate-500">"{example.text}"</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // Connected - ready to ship
  return (
    <div className="flex flex-col items-center justify-center h-full text-center px-4 animate-fade-in">
      <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-success/20 to-success/10 border border-success/30 flex items-center justify-center mb-6">
        <PackageIcon className="w-8 h-8 text-success" />
      </div>

      <h2 className="text-xl font-semibold text-slate-100 mb-2">
        Ready to Ship
      </h2>

      <p className="text-sm text-slate-400 max-w-md mb-2">
        Connected to <span className="text-amber-400 font-medium">{dataSource.type.toUpperCase()}</span>
        {dataSource.row_count && (
          <> with <span className="text-amber-400 font-medium">{dataSource.row_count.toLocaleString()}</span> rows</>
        )}
      </p>

      <p className="text-xs text-slate-500 max-w-md mb-8">
        Describe what you want to ship in natural language. ShipAgent will parse your intent,
        filter your data, and generate a preview for your approval.
      </p>

      {/* Clickable examples */}
      <div className="space-y-3 w-full max-w-md">
        <p className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Click to try</p>
        <div className="space-y-2">
          {examples.map((example, i) => (
            <button
              key={i}
              onClick={() => onExampleClick?.(example.text)}
              className="w-full px-4 py-3 rounded-lg bg-slate-800/50 border border-slate-700/50 text-left hover:bg-slate-800 hover:border-slate-600 transition-colors group"
            >
              <p className="text-sm text-slate-300 group-hover:text-slate-100">"{example.text}"</p>
              <p className="text-[10px] text-slate-600 mt-0.5">{example.desc}</p>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

// Main CommandCenter component
export function CommandCenter({ activeJob: _activeJob }: CommandCenterProps) {
  const {
    dataSource,
    conversation,
    addMessage,
    isProcessing,
    setIsProcessing,
    setActiveJob,
  } = useAppState();

  const [inputValue, setInputValue] = React.useState('');
  const [preview, setPreview] = React.useState<BatchPreview | null>(null);
  const [currentJobId, setCurrentJobId] = React.useState<string | null>(null);
  const [isConfirming, setIsConfirming] = React.useState(false);
  const [executingJobId, setExecutingJobId] = React.useState<string | null>(null);

  const messagesEndRef = React.useRef<HTMLDivElement>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);

  // Auto-scroll to bottom
  React.useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [conversation, preview, executingJobId]);

  // Handle command submit
  const handleSubmit = async () => {
    const command = inputValue.trim();
    if (!command || isProcessing || !dataSource) return;

    setInputValue('');
    setIsProcessing(true);

    // Add user message
    addMessage({ role: 'user', content: command });

    try {
      // Submit command to backend
      const result = await submitCommand(command);
      setCurrentJobId(result.job_id);

      // Fetch preview
      const previewData = await getJobPreview(result.job_id);
      setPreview(previewData);

      // Add system response
      addMessage({
        role: 'system',
        content: `Found ${previewData.total_rows} matching rows. Estimated cost: ${formatCurrency(previewData.total_estimated_cost_cents)}.\n\nReview the preview below and confirm to proceed.`,
        metadata: {
          jobId: result.job_id,
          action: 'preview',
          preview: {
            rowCount: previewData.total_rows,
            estimatedCost: previewData.total_estimated_cost_cents,
            warnings: previewData.rows_with_warnings,
          },
        },
      });
    } catch (err) {
      addMessage({
        role: 'system',
        content: `Error: ${err instanceof Error ? err.message : 'Failed to process command'}`,
        metadata: { action: 'error' },
      });
    } finally {
      setIsProcessing(false);
    }
  };

  // Handle confirm
  const handleConfirm = async () => {
    if (!currentJobId) return;

    setIsConfirming(true);
    try {
      await confirmJob(currentJobId);
      setExecutingJobId(currentJobId);
      setPreview(null);

      addMessage({
        role: 'system',
        content: 'Batch confirmed. Processing shipments...',
        metadata: { jobId: currentJobId, action: 'execute' },
      });

      // Fetch job and set as active
      const job = await getJob(currentJobId);
      setActiveJob(job);
    } catch (err) {
      addMessage({
        role: 'system',
        content: `Error: ${err instanceof Error ? err.message : 'Failed to confirm batch'}`,
        metadata: { action: 'error' },
      });
    } finally {
      setIsConfirming(false);
    }
  };

  // Handle cancel
  const handleCancel = async () => {
    if (!currentJobId) return;

    try {
      await cancelJob(currentJobId);
      setPreview(null);
      setCurrentJobId(null);

      addMessage({
        role: 'system',
        content: 'Batch cancelled. You can enter a new command.',
      });
    } catch (err) {
      console.error('Failed to cancel:', err);
    }
  };

  // Handle key press
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Messages area */}
      <div className="flex-1 overflow-y-auto scrollable p-6">
        {conversation.length === 0 && !preview && !executingJobId ? (
          <WelcomeMessage onExampleClick={(text) => setInputValue(text)} />
        ) : (
          <div className="max-w-3xl mx-auto space-y-6">
            {conversation.map((message) => (
              message.role === 'user' ? (
                <UserMessage key={message.id} message={message} />
              ) : (
                <SystemMessage key={message.id} message={message} />
              )
            ))}

            {/* Preview card */}
            {preview && !executingJobId && (
              <div className="pl-11">
                <PreviewCard
                  preview={preview}
                  onConfirm={handleConfirm}
                  onCancel={handleCancel}
                  isConfirming={isConfirming}
                />
              </div>
            )}

            {/* Progress display */}
            {executingJobId && (
              <div className="pl-11">
                <ProgressDisplay jobId={executingJobId} />
              </div>
            )}

            {/* Typing indicator */}
            {isProcessing && <TypingIndicator />}

            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Input area */}
      <div className="border-t border-slate-800 p-4 bg-void-900/50 backdrop-blur">
        <div className="max-w-3xl mx-auto">
          <div className="flex gap-3">
            <div className="relative flex-1">
              <input
                ref={inputRef}
                type="text"
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={
                  !dataSource
                    ? 'Connect a data source to begin...'
                    : 'Enter a shipping command...'
                }
                disabled={!dataSource || isProcessing || !!preview}
                className={cn(
                  'input-command pr-12',
                  (!dataSource || isProcessing || !!preview) && 'opacity-50 cursor-not-allowed'
                )}
              />

              {/* Character count */}
              {inputValue.length > 0 && (
                <span className="absolute right-4 top-1/2 -translate-y-1/2 text-[10px] font-mono text-slate-500">
                  {inputValue.length}
                </span>
              )}
            </div>

            <button
              onClick={handleSubmit}
              disabled={!inputValue.trim() || !dataSource || isProcessing || !!preview}
              className={cn(
                'btn-primary px-5',
                (!inputValue.trim() || !dataSource || isProcessing || !!preview) && 'opacity-50 cursor-not-allowed'
              )}
            >
              {isProcessing ? (
                <span className="w-5 h-5 border-2 border-void-950/30 border-t-void-950 rounded-full animate-spin" />
              ) : executingJobId ? (
                <StopIcon className="w-5 h-5" />
              ) : (
                <SendIcon className="w-5 h-5" />
              )}
            </button>
          </div>

          {/* Help text */}
          <div className="flex items-center justify-between mt-2">
            <p className="text-[10px] font-mono text-slate-500">
              {dataSource
                ? 'Describe what you want to ship in natural language'
                : 'Connect a data source from the sidebar'}
            </p>
            <p className="text-[10px] font-mono text-slate-600">
              Press <kbd className="px-1 py-0.5 rounded bg-slate-800 border border-slate-700">Enter</kbd> to send
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

export default CommandCenter;
