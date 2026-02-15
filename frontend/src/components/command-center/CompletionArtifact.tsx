/**
 * Inline card for completed batches in the chat thread.
 *
 * Shows status badge, cost, shipment count, per-row failures,
 * and a label download button.
 */

import { cn, formatCurrency } from '@/lib/utils';
import type { ConversationMessage } from '@/hooks/useAppState';
import { DownloadIcon } from '@/components/ui/icons';

const MAX_VISIBLE_REFINEMENTS = 3;

/** Parse a job name that may contain → delimiters into base command and refinements. */
export function parseRefinedName(name: string | undefined): { base: string; refinements: string[]; overflow: number } {
  if (!name || !name.includes(' → ')) return { base: name || '', refinements: [], overflow: 0 };
  const parts = name.split(' → ');
  const base = parts[0];
  const allRefinements = parts.slice(1);
  const overflow = Math.max(0, allRefinements.length - MAX_VISIBLE_REFINEMENTS);
  const refinements = allRefinements.slice(0, MAX_VISIBLE_REFINEMENTS);
  return { base, refinements, overflow };
}

/** Inline card for completed batches (green/amber/red border, label access). */
export function CompletionArtifact({ message, onViewLabels }: {
  message: ConversationMessage;
  onViewLabels: (jobId: string) => void;
}) {
  const meta = message.metadata?.completion;
  const jobId = message.metadata?.jobId;
  if (!meta || !jobId) return null;

  const allFailed = meta.successful === 0 && meta.failed > 0;
  const hasFailures = meta.failed > 0;
  const borderColor = allFailed ? 'border-l-error' : hasFailures ? 'border-l-warning' : 'border-l-success';
  const badgeClass = allFailed ? 'badge-error' : hasFailures ? 'badge-warning' : 'badge-success';
  const badgeText = allFailed ? 'FAILED' : hasFailures ? 'PARTIAL' : 'COMPLETED';

  const displayName = meta.jobName || `Command: ${meta.command}`;
  const { base, refinements, overflow } = parseRefinedName(displayName);
  const baseDisplay = base.startsWith('Command: ') ? base.slice(9) : base;

  return (
    <div className={cn(
      'card-premium p-4 space-y-3 border-l-4',
      borderColor
    )}>
      <div className="flex justify-end">
        <span className={cn('badge', badgeClass)}>{badgeText}</span>
      </div>

      <div className="space-y-1">
        <p className="text-xs text-slate-400 italic truncate">&ldquo;{baseDisplay}&rdquo;</p>
        {refinements.map((ref, i) => (
          <p key={i} className="text-[11px] text-primary/80 truncate">
            &rarr; {ref}
          </p>
        ))}
        {overflow > 0 && (
          <p className="text-[10px] text-slate-500 italic">
            +{overflow} more refinement{overflow !== 1 ? 's' : ''}
          </p>
        )}
      </div>

      <div className="flex items-center gap-3 text-xs font-mono text-slate-400">
        <span>{meta.successful} shipment{meta.successful !== 1 ? 's' : ''}</span>
        <span className="text-slate-600">&middot;</span>
        <span className="text-primary">{formatCurrency(meta.totalCostCents)}</span>
        {meta.failed > 0 && (
          <>
            <span className="text-slate-600">&middot;</span>
            <span className="text-error">{meta.failed} failed</span>
          </>
        )}
      </div>

      {/* Per-row failure details */}
      {meta.rowFailures && meta.rowFailures.length > 0 && (
        <div className="space-y-1 max-h-[100px] overflow-y-auto scrollable">
          {meta.rowFailures.map((f) => (
            <div key={f.rowNumber} className="flex items-start gap-2 px-2 py-1.5 rounded bg-error/10 border border-error/20">
              <span className="text-[10px] font-mono text-error/70 flex-shrink-0 mt-px">
                Row {f.rowNumber}
              </span>
              <span className="text-[10px] font-mono text-error/90 break-all">
                {f.errorMessage}
              </span>
            </div>
          ))}
        </div>
      )}

      {!allFailed && (
        <button
          onClick={() => onViewLabels(jobId)}
          className="w-full btn-primary py-2 flex items-center justify-center gap-2 text-sm"
        >
          <DownloadIcon className="w-3.5 h-3.5" />
          <span>View Labels (PDF)</span>
        </button>
      )}
    </div>
  );
}
