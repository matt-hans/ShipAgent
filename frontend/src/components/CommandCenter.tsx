/**
 * CommandCenter - Conversational interface orchestrator shell.
 */

import * as React from 'react';
import { useAppState } from '@/hooks/useAppState';
import { cn } from '@/lib/utils';
import { confirmJob, cancelJob, deleteJob, getJob, getMergedLabelsUrl, skipRows } from '@/lib/api';
import { useConversation } from '@/hooks/useConversation';
import type { Job, BatchPreview, PickupResult, PickupPreview, LocationResult, LandedCostResult, PaperlessResult, TrackingResult } from '@/types/api';
import { LabelPreview } from '@/components/LabelPreview';
import { JobDetailPanel } from '@/components/JobDetailPanel';
import { SendIcon, StopIcon, EditIcon } from '@/components/ui/icons';
import { PreviewCard, InteractivePreviewCard, type ConfirmOptions } from '@/components/command-center/PreviewCard';
import { ProgressDisplay } from '@/components/command-center/ProgressDisplay';
import { CompletionArtifact } from '@/components/command-center/CompletionArtifact';
import { ToolCallChip } from '@/components/command-center/ToolCallChip';
import { PickupCard } from '@/components/command-center/PickupCard';
import { PickupPreviewCard } from '@/components/command-center/PickupPreviewCard';
import { PickupCompletionCard } from '@/components/command-center/PickupCompletionCard';
import { LocationCard } from '@/components/command-center/LocationCard';
import { LandedCostCard } from '@/components/command-center/LandedCostCard';
import { PaperlessCard } from '@/components/command-center/PaperlessCard';
import { TrackingCard } from '@/components/command-center/TrackingCard';
import {
  ActiveSourceBanner,
  InteractiveModeBanner,
  SystemMessage,
  TypingIndicator,
  UserMessage,
  WelcomeMessage,
} from '@/components/command-center/messages';

interface CommandCenterProps {
  activeJob: Job | null;
}

export function CommandCenter({ activeJob }: CommandCenterProps) {
  const {
    conversation,
    addMessage,
    clearConversation,
    isProcessing,
    setIsProcessing,
    setActiveJob,
    refreshJobList,
    activeSourceType,
    warningPreference,
    setConversationSessionId,
    interactiveShipping,
    setInteractiveShipping,
    writeBackEnabled,
    setIsToggleLocked,
  } = useAppState();

  const hasDataSource = activeSourceType !== null;
  const canInput = true;

  // Agent-driven conversation hook
  const conv = useConversation();

  const [inputValue, setInputValue] = React.useState('');
  const [preview, setPreview] = React.useState<BatchPreview | null>(null);
  const [currentJobId, setCurrentJobId] = React.useState<string | null>(null);
  const [isConfirming, setIsConfirming] = React.useState(false);
  const [executingJobId, setExecutingJobId] = React.useState<string | null>(null);
  const [showLabelPreview, setShowLabelPreview] = React.useState(false);
  const [labelPreviewJobId, setLabelPreviewJobId] = React.useState<string | null>(null);
  const [isRefining, setIsRefining] = React.useState(false);
  const [pickupPreview, setPickupPreview] = React.useState<PickupPreview | null>(null);
  const [isPickupConfirming, setIsPickupConfirming] = React.useState(false);

  const messagesEndRef = React.useRef<HTMLDivElement>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const lastCommandRef = React.useRef<string>('');
  const lastJobNameRef = React.useRef<string>('');
  const prevInteractiveRef = React.useRef(interactiveShipping);
  const [isResettingSession, setIsResettingSession] = React.useState(false);

  // Reset session when interactive shipping mode changes.
  //
  // Handles two distinct cases:
  // 1. Active session exists (sessionId is set) → reset and recreate on next send.
  // 2. Session creation in-flight (isCreatingSession) → wait for it, then reset,
  //    so the next send creates a session with the correct mode.
  React.useEffect(() => {
    if (prevInteractiveRef.current === interactiveShipping) return;
    prevInteractiveRef.current = interactiveShipping;

    const hasActiveOrInflightSession = conv.sessionId || conv.isCreatingSession;
    if (!hasActiveOrInflightSession) return;

    // Confirm if there's in-progress work
    if (preview || conv.isProcessing) {
      const confirmed = window.confirm(
        'Switching mode resets your current session. Continue?'
      );
      if (!confirmed) {
        // Revert toggle
        setInteractiveShipping(!interactiveShipping);
        prevInteractiveRef.current = !interactiveShipping;
        return;
      }
    }

    // Race-safe reset: wait for any in-flight creation to settle, then reset.
    setIsResettingSession(true);
    setIsToggleLocked(true);
    const doReset = async () => {
      // If a creation is in-flight, the mutex promise settles once complete.
      // reset() then tears it down so the next send creates a fresh session.
      await conv.reset();
      clearConversation();
      setPreview(null);
      setCurrentJobId(null);
      setExecutingJobId(null);
      setIsRefining(false);
      setPickupPreview(null);
      setIsPickupConfirming(false);
      setShowLabelPreview(false);
      setLabelPreviewJobId(null);
      setIsResettingSession(false);
      setIsToggleLocked(false);
    };
    doReset();
  }, [
    interactiveShipping,
    conv.sessionId,
    conv.isCreatingSession,
    conv.isProcessing,
    preview,
    setInteractiveShipping,
    setIsToggleLocked,
    conv.reset,
    clearConversation,
  ]);

  // Lock toggle while session creation is in-flight or agent is processing.
  // (Reset-driven locking is handled in the toggle-change effect above.)
  React.useEffect(() => {
    if (conv.isCreatingSession || conv.isProcessing) {
      setIsToggleLocked(true);
    } else if (!isResettingSession) {
      // Only unlock if we're not mid-reset (the reset effect unlocks itself).
      setIsToggleLocked(false);
    }
  }, [conv.isCreatingSession, conv.isProcessing, isResettingSession, setIsToggleLocked]);

  // Sync conversation session ID to AppState
  React.useEffect(() => {
    setConversationSessionId(conv.sessionId);
  }, [conv.sessionId, setConversationSessionId]);

  // Render agent events as conversation messages
  const lastProcessedEventRef = React.useRef(0);
  const suppressNextMessageRef = React.useRef(false);
  const wasProcessingRef = React.useRef(false);
  React.useEffect(() => {
    if (conv.events.length < lastProcessedEventRef.current) {
      lastProcessedEventRef.current = 0;
    }
    const newEvents = conv.events.slice(lastProcessedEventRef.current);
    lastProcessedEventRef.current = conv.events.length;

    for (const event of newEvents) {
      if (event.type === 'agent_message') {
        if (suppressNextMessageRef.current) {
          suppressNextMessageRef.current = false;
          continue;
        }
        const text = (event.data.text as string) || '';
        // Suppress synthetic SDK error from hook denials (claude-agent-sdk-python#265)
        if (text && !text.includes('API Error: 400 due to tool use concurrency issues')) {
          addMessage({ role: 'system', content: text });
        }
      } else if (event.type === 'preview_ready') {
        const previewData = event.data as unknown as BatchPreview;
        const previousJobId = currentJobId;
        const nextJobId = previewData.job_id;

        setPreview(previewData);
        setCurrentJobId(nextJobId);
        setIsRefining(false);
        refreshJobList();
        addMessage({
          role: 'system',
          content: 'Preview ready — please review and click Confirm or Cancel.',
        });

        // Refinement previews may come back as a new pending job id.
        // Keep history to one active pending entry by removing the superseded preview job.
        if (
          previousJobId &&
          nextJobId &&
          previousJobId !== nextJobId &&
          preview &&
          !executingJobId
        ) {
          void Promise.resolve(deleteJob(previousJobId))
            .catch((err) => {
              console.warn('Failed to remove superseded preview job:', err);
            })
            .finally(() => {
              refreshJobList();
            });
        }
        suppressNextMessageRef.current = true;
      } else if (event.type === 'error') {
        const msg = (event.data.message as string) || 'Agent error';
        setIsRefining(false);
        addMessage({
          role: 'system',
          content: `Error: ${msg}`,
          metadata: { action: 'error' },
        });
      } else if (event.type === 'pickup_preview') {
        const previewData = event.data as unknown as PickupPreview;
        setPickupPreview(previewData);
        addMessage({
          role: 'system',
          content: '',
          metadata: { action: 'pickup_preview' as any, pickupPreview: previewData },
        });
        suppressNextMessageRef.current = true;
      } else if (event.type === 'pickup_result') {
        addMessage({
          role: 'system',
          content: '',
          metadata: { action: 'pickup_result', pickup: event.data as unknown as PickupResult },
        });
        suppressNextMessageRef.current = true;
      } else if (event.type === 'location_result') {
        addMessage({
          role: 'system',
          content: '',
          metadata: { action: 'location_result', location: event.data as unknown as LocationResult },
        });
        suppressNextMessageRef.current = true;
      } else if (event.type === 'landed_cost_result') {
        addMessage({
          role: 'system',
          content: '',
          metadata: { action: 'landed_cost_result', landedCost: event.data as unknown as LandedCostResult },
        });
        suppressNextMessageRef.current = true;
      } else if (event.type === 'paperless_result') {
        addMessage({
          role: 'system',
          content: '',
          metadata: { action: 'paperless_result', paperless: event.data as unknown as PaperlessResult },
        });
        suppressNextMessageRef.current = true;
      } else if (event.type === 'tracking_result') {
        addMessage({
          role: 'system',
          content: '',
          metadata: { action: 'tracking_result', tracking: event.data as unknown as TrackingResult },
        });
        suppressNextMessageRef.current = true;
      }
    }
  }, [conv.events, addMessage, refreshJobList, currentJobId, preview, executingJobId]);

  // Clear transient agent events after each completed run to bound memory.
  React.useEffect(() => {
    if (wasProcessingRef.current && !conv.isProcessing) {
      suppressNextMessageRef.current = false;
      lastProcessedEventRef.current = 0;
      conv.clearEvents();
    }
    wasProcessingRef.current = conv.isProcessing;
  }, [conv.isProcessing, conv.clearEvents]);

  // Sync processing state from conversation hook
  React.useEffect(() => {
    setIsProcessing(conv.isProcessing);
  }, [conv.isProcessing, setIsProcessing]);

  // Auto-scroll to bottom (includes activeJob so returning from job detail scrolls down)
  React.useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [conversation, preview, executingJobId, activeJob, conv.events]);

  // Handle command submit — uses agent-driven conversation flow
  const handleSubmit = async () => {
    const command = inputValue.trim();
    if (!command || isProcessing || !canInput) return;

    lastCommandRef.current = command;
    setInputValue('');

    // Add user message
    addMessage({ role: 'user', content: command });

    // Send via agent conversation — the hook manages SSE events,
    // which are rendered as system messages via the effect above
    await conv.sendMessage(command, interactiveShipping);
  };

  // Handle confirm with optional row skipping
  const handleConfirm = async (opts?: ConfirmOptions) => {
    if (!currentJobId) return;

    setIsConfirming(true);
    // refinement state cleared
    try {
      // Skip warning rows if explicitly requested or if preference is 'skip-warnings'
      if (opts?.skipWarningRows && opts.warningRowNumbers?.length) {
        await skipRows(currentJobId, opts.warningRowNumbers);
      }

      await confirmJob(currentJobId, writeBackEnabled);
      setExecutingJobId(currentJobId);
      setPreview(null);

      addMessage({
        role: 'system',
        content: opts?.skipWarningRows
          ? `Batch confirmed. Skipped ${opts.warningRowNumbers?.length ?? 0} warning row(s). Processing remaining shipments...`
          : 'Batch confirmed. Processing shipments...',
        metadata: { jobId: currentJobId, action: 'execute' },
      });

      // Fetch job to capture its display name (includes → refinements)
      const job = await getJob(currentJobId);
      lastJobNameRef.current = job.name || '';
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

    // refinement state cleared
    try {
      await cancelJob(currentJobId);
      setPreview(null);
      setCurrentJobId(null);
      refreshJobList();

      addMessage({
        role: 'system',
        content: 'Batch cancelled. You can enter a new command.',
      });
    } catch (err) {
      console.error('Failed to cancel:', err);
    }
  };

  // Handle refinement — send as a follow-up conversation message
  const handleRefine = async (refinementText: string) => {
    if (!refinementText.trim() || isRefining) return;
    if (conv.isProcessing) {
      addMessage({
        role: 'system',
        content: 'Please wait for the current update to finish, then try refining again.',
      });
      return;
    }

    setIsRefining(true);
    try {
      // Send refinement through the agent conversation
      await conv.sendMessage(refinementText.trim(), interactiveShipping);
    } catch (err) {
      setIsRefining(false);
      addMessage({
        role: 'system',
        content: `Refinement failed: ${err instanceof Error ? err.message : 'Unknown error'}.`,
        metadata: { action: 'error' },
      });
    }
  };

  // Handle key press
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  // Show job detail panel when a sidebar job is selected (takes priority over conversation)
  const showJobDetail = activeJob && !preview && !executingJobId;

  if (showJobDetail) {
    return (
      <JobDetailPanel
        job={activeJob}
        onBack={() => {
          // Clear any lingering label preview state before returning to chat
          // so the modal doesn't flash open on re-render
          setShowLabelPreview(false);
          setLabelPreviewJobId(null);
          setActiveJob(null);
        }}
      />
    );
  }

  return (
    <div className={cn('flex flex-col h-full', interactiveShipping && 'command-center--interactive')}>
      {interactiveShipping ? <InteractiveModeBanner /> : <ActiveSourceBanner />}
      {/* Messages area */}
      <div className="command-messages-shell flex-1 overflow-y-auto scrollable p-6">
        {conversation.length === 0 && !preview && !executingJobId ? (
          <WelcomeMessage onExampleClick={(text) => setInputValue(text)} interactiveShipping={interactiveShipping} />
        ) : (
          <div className="max-w-3xl mx-auto space-y-6">
            {conversation.map((message) => (
              message.metadata?.action === 'complete' ? (
                <div key={message.id} className="pl-11">
                  <CompletionArtifact
                    message={message}
                    onViewLabels={(jobId) => {
                      setLabelPreviewJobId(jobId);
                      setShowLabelPreview(true);
                    }}
                    onSendMessage={(text) => {
                      setInputValue(text);
                    }}
                  />
                </div>
              ) : message.metadata?.action === 'pickup_preview' && message.metadata.pickupPreview ? (
                <div key={message.id} className="pl-11">
                  <PickupPreviewCard
                    data={message.metadata.pickupPreview}
                    onConfirm={async () => {
                      setIsPickupConfirming(true);
                      try {
                        await conv.sendMessage('Confirmed. Schedule the pickup.', interactiveShipping);
                      } finally {
                        setIsPickupConfirming(false);
                        setPickupPreview(null);
                      }
                    }}
                    onCancel={() => {
                      setPickupPreview(null);
                      addMessage({ role: 'system', content: 'Pickup cancelled.' });
                    }}
                    isConfirming={isPickupConfirming}
                  />
                </div>
              ) : message.metadata?.action === 'pickup_result' && message.metadata.pickup ? (
                <div key={message.id} className="pl-11">
                  {message.metadata.pickup.action === 'scheduled' ? (
                    <PickupCompletionCard data={message.metadata.pickup} />
                  ) : (
                    <PickupCard data={message.metadata.pickup} />
                  )}
                </div>
              ) : message.metadata?.action === 'location_result' && message.metadata.location ? (
                <div key={message.id} className="pl-11">
                  <LocationCard data={message.metadata.location} />
                </div>
              ) : message.metadata?.action === 'landed_cost_result' && message.metadata.landedCost ? (
                <div key={message.id} className="pl-11">
                  <LandedCostCard data={message.metadata.landedCost} />
                </div>
              ) : message.metadata?.action === 'paperless_result' && message.metadata.paperless ? (
                <div key={message.id} className="pl-11">
                  <PaperlessCard data={message.metadata.paperless} />
                </div>
              ) : message.metadata?.action === 'tracking_result' && message.metadata.tracking ? (
                <div key={message.id} className="pl-11">
                  <TrackingCard data={message.metadata.tracking} />
                </div>
              ) : message.role === 'user' ? (
                <UserMessage key={message.id} message={message} />
              ) : (
                <SystemMessage key={message.id} message={message} />
              )
            ))}

            {/* Preview card */}
            {preview && !executingJobId && (
              <div className="pl-11">
                {preview.interactive ? (
                  <InteractivePreviewCard
                    preview={preview}
                    onConfirm={(opts) => handleConfirm(opts)}
                    onCancel={handleCancel}
                    isConfirming={isConfirming}
                    isProcessing={conv.isProcessing}
                  />
                ) : (
                  <PreviewCard
                    preview={preview}
                    onConfirm={(opts) => {
                      // Apply preference-based auto-behavior for non-'ask' modes
                      if (warningPreference === 'ship-all') {
                        handleConfirm();
                      } else if (warningPreference === 'skip-warnings') {
                        const warnRows = preview.preview_rows.filter(
                          (r) => r.warnings?.length
                        );
                        if (warnRows.length > 0) {
                          handleConfirm({
                            skipWarningRows: true,
                            warningRowNumbers: warnRows.map((r) => r.row_number),
                          });
                        } else {
                          handleConfirm();
                        }
                      } else {
                        // 'ask' mode — pass through from gate
                        handleConfirm(opts);
                      }
                    }}
                    onCancel={handleCancel}
                    isConfirming={isConfirming}
                    onRefine={handleRefine}
                    isRefining={isRefining}
                    isProcessing={conv.isProcessing}
                    warningPreference={warningPreference}
                  />
                )}
              </div>
            )}

            {/* Progress display */}
            {executingJobId && (
              <div className="pl-11">
                <ProgressDisplay
                  jobId={executingJobId}
                  onComplete={(data) => {
                    addMessage({
                      role: 'system',
                      content: '',
                      metadata: {
                        jobId: executingJobId,
                        action: 'complete' as const,
                        completion: {
                          command: lastCommandRef.current,
                          jobName: lastJobNameRef.current || undefined,
                          totalRows: data.total,
                          successful: data.successful,
                          failed: data.failed,
                          totalCostCents: data.totalCostCents,
                          dutiesTaxesCents: data.dutiesTaxesCents,
                          internationalCount: data.internationalCount,
                          rowFailures: data.rowFailures.length > 0 ? data.rowFailures : undefined,
                        },
                      },
                    });
                    setLabelPreviewJobId(executingJobId);
                    setShowLabelPreview(true);
                    setExecutingJobId(null);
                    setCurrentJobId(null);
                    setActiveJob(null);
                    refreshJobList();
                  }}
                  onFailed={(data) => {
                    addMessage({
                      role: 'system',
                      content: '',
                      metadata: {
                        jobId: executingJobId,
                        action: 'complete' as const,
                        completion: {
                          command: lastCommandRef.current,
                          jobName: lastJobNameRef.current || undefined,
                          totalRows: data.total,
                          successful: data.successful,
                          failed: data.failed,
                          totalCostCents: data.totalCostCents,
                          dutiesTaxesCents: data.dutiesTaxesCents,
                          internationalCount: data.internationalCount,
                          rowFailures: data.rowFailures.length > 0 ? data.rowFailures : undefined,
                        },
                      },
                    });
                    if (data.successful > 0) {
                      setLabelPreviewJobId(executingJobId);
                      setShowLabelPreview(true);
                    }
                    setExecutingJobId(null);
                    setCurrentJobId(null);
                    setActiveJob(null);
                    refreshJobList();
                  }}
                />
              </div>
            )}

            {/* Current tool call chip — only show active latest tool */}
            {conv.isProcessing && !preview && (() => {
              const lastToolCall = conv.events.filter((e) => e.type === 'tool_call').at(-1);
              return lastToolCall ? <ToolCallChip key={lastToolCall.id} event={lastToolCall} /> : null;
            })()}

            {/* Typing indicator — shown during initial processing or refinement */}
            {isProcessing && !preview && <TypingIndicator />}
            {isRefining && (
              <div className="flex gap-3 animate-fade-in">
                <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-gradient-to-br from-primary/20 to-primary/30 border border-primary/30 flex items-center justify-center">
                  <EditIcon className="w-4 h-4 text-primary animate-pulse" />
                </div>
                <div className="message-system py-3">
                  <div className="flex items-center gap-2">
                    <span className="w-3.5 h-3.5 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
                    <span className="text-xs text-slate-400">Recalculating rates...</span>
                  </div>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Input area */}
      <div className="command-input-shell border-t border-slate-800 px-4 py-3 bg-void-900/50 backdrop-blur">
        <div className="max-w-3xl mx-auto">
          <div className="flex gap-2">
            <div className="relative flex-1">
              <input
                ref={inputRef}
                type="text"
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={
                  interactiveShipping
                    ? 'Describe one shipment from scratch...'
                    : !hasDataSource
                        ? 'Track a package, find locations, or connect a data source...'
                        : 'Enter a shipping command...'
                }
                disabled={!canInput || isProcessing || !!preview || !!executingJobId || !!pickupPreview || isResettingSession}
                className={cn(
                  'input-command pr-12',
                  (!canInput || isProcessing || !!preview || !!executingJobId || !!pickupPreview || isResettingSession) && 'opacity-50 cursor-not-allowed'
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
              disabled={!inputValue.trim() || !canInput || isProcessing || !!preview || !!executingJobId || !!pickupPreview || isResettingSession}
              className={cn(
                'btn-primary px-4',
                (!inputValue.trim() || !canInput || isProcessing || !!preview || !!executingJobId || !!pickupPreview || isResettingSession) && 'opacity-50 cursor-not-allowed'
              )}
            >
              {isProcessing ? (
                <span className="w-4 h-4 border-2 border-void-950/30 border-t-void-950 rounded-full animate-spin" />
              ) : executingJobId ? (
                <StopIcon className="w-4 h-4" />
              ) : (
                <SendIcon className="w-4 h-4" />
              )}
            </button>
          </div>

          {/* Help text - single line */}
          <p className="text-[10px] font-mono text-slate-500 mt-1.5">
            {interactiveShipping
              ? 'Ad-hoc mode — provide shipment details; ShipAgent will ask for missing fields'
              : hasDataSource
                ? 'Describe what you want to ship in natural language'
                : 'Tracking, pickup, location, and landed cost tools available without a data source'} · Press <kbd className="px-1 py-0.5 rounded bg-slate-800 border border-slate-700">Enter</kbd> to send
          </p>
        </div>
      </div>

      {/* Label preview modal - shown on batch completion or artifact click */}
      {labelPreviewJobId && (
        <LabelPreview
          pdfUrl={getMergedLabelsUrl(labelPreviewJobId)}
          title="Batch Labels"
          isOpen={showLabelPreview}
          onClose={() => {
            setShowLabelPreview(false);
            setLabelPreviewJobId(null);
          }}
        />
      )}
    </div>
  );
}

export default CommandCenter;
