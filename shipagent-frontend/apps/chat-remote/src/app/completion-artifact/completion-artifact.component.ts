/**
 * CompletionArtifactComponent — Inline card for completed batches in the chat thread.
 *
 * Shows status badge (completed/partial/failed), cost, shipment count,
 * per-row failures, and a label download button. Matches React's
 * CompletionArtifact component with refinement chain display.
 */

import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  FormatCurrencyPipe,
  DownloadIconComponent,
} from '@shipagent/shared-ui';
import type {
  ConversationMessage,
  JobTerminalStatus,
  SafeTerminalDiagnostic,
  SafeTerminalRowDiagnostic,
} from '@shipagent/shared-types';

const MAX_VISIBLE_REFINEMENTS = 3;
type CompletionPresentation =
  | 'completed'
  | 'warning'
  | 'partial'
  | 'failed'
  | 'cancelled';

/** Typed shape of the completion metadata from ConversationMessage. */
interface CompletionMeta {
  status?: JobTerminalStatus;
  outcome?: 'complete' | 'failed';
  hasWarnings?: boolean;
  cancelled?: boolean;
  statusMessage?: string;
  error?: SafeTerminalDiagnostic;
  successful: number;
  failed: number;
  totalCostCents: number;
  dutiesTaxesCents?: number | null;
  internationalCount?: number | null;
  row_failures?: SafeTerminalRowDiagnostic[];
  omitted_failure_count?: number;
  jobName?: string;
  command?: string;
}

/** Parse a job name that may contain → delimiters into base command and refinements. */
function parseRefinedName(name: string | undefined): {
  base: string;
  refinements: string[];
  overflow: number;
} {
  if (!name || !name.includes(' → '))
    return { base: name || '', refinements: [], overflow: 0 };
  const parts = name.split(' → ');
  const base = parts[0];
  const allRefinements = parts.slice(1);
  const overflow = Math.max(0, allRefinements.length - MAX_VISIBLE_REFINEMENTS);
  const refinements = allRefinements.slice(0, MAX_VISIBLE_REFINEMENTS);
  return { base, refinements, overflow };
}

@Component({
  selector: 'app-completion-artifact',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormatCurrencyPipe, DownloadIconComponent],
  template: `
    @if (meta && jobId) {
    <div
      class="card-premium p-4 space-y-3 border-l-4"
      [class.border-l-error]="allFailed"
      [class.border-l-warning]="
        !allFailed && (hasFailures || hasWarnings || isCancelled)
      "
      [class.border-l-success]="
        !allFailed && !hasFailures && !hasWarnings && !isCancelled
      "
    >
      <div class="flex justify-end">
        <span
          class="badge"
          [class.badge-error]="allFailed"
          [class.badge-warning]="
            !allFailed && (hasFailures || hasWarnings || isCancelled)
          "
          [class.badge-success]="
            !allFailed && !hasFailures && !hasWarnings && !isCancelled
          "
        >
          {{ badgeText }}
        </span>
      </div>

      @if ((allFailed || hasWarnings || isCancelled) && (meta.statusMessage ||
      meta.error)) {
      <div class="max-h-[100px] overflow-y-auto space-y-1">
        @if (meta.statusMessage) {
        <p
          class="text-xs font-mono"
          [class.text-error]="allFailed"
          [class.text-warning]="!allFailed"
        >
          {{ meta.statusMessage }}
        </p>
        } @if (meta.error) {
        <p
          class="text-xs font-mono"
          [class.text-error]="allFailed"
          [class.text-warning]="!allFailed"
        >
          {{ meta.error.error_code }}: {{ meta.error.message }}
        </p>
        }
      </div>
      }

      <!-- Job name with refinements -->
      <div class="space-y-1">
        <p class="text-xs text-slate-400 italic truncate">
          &ldquo;{{ baseDisplay }}&rdquo;
        </p>
        @for (ref of refinements; track $index) {
        <p class="text-[11px] text-primary/80 truncate">&rarr; {{ ref }}</p>
        } @if (overflow > 0) {
        <p class="text-[10px] text-slate-500 italic">
          +{{ overflow }} more refinement{{ overflow !== 1 ? 's' : '' }}
        </p>
        }
      </div>

      <!-- Stats -->
      <div class="flex items-center gap-3 text-xs font-mono text-slate-400">
        <span
          >{{ meta.successful }} shipment{{
            meta.successful !== 1 ? 's' : ''
          }}</span
        >
        <span class="text-slate-600">&middot;</span>
        <span class="text-primary">{{
          meta.totalCostCents | formatCurrency
        }}</span>
        @if ((meta.dutiesTaxesCents ?? 0) > 0) {
        <span class="text-slate-600">&middot;</span>
        <span class="text-amber-400"
          >{{ meta.dutiesTaxesCents | formatCurrency }} duties</span
        >
        } @if (meta.failed > 0) {
        <span class="text-slate-600">&middot;</span>
        <span class="text-error">{{ meta.failed }} failed</span>
        } @if ((meta.internationalCount ?? 0) > 0) {
        <span class="text-slate-600">&middot;</span>
        <span
          class="px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400 text-[8px] font-medium"
        >
          {{ meta.internationalCount }} INTL
        </span>
        }
      </div>

      <!-- Per-row failure details -->
      @if (meta.row_failures && meta.row_failures.length > 0) {
      <div class="space-y-1 max-h-[100px] overflow-y-auto">
        @for (f of meta.row_failures; track f.row_number) {
        <div
          class="flex items-start gap-2 px-2 py-1.5 rounded bg-error/10 border border-error/20"
        >
          <span class="text-[10px] font-mono text-error/70 flex-shrink-0 mt-px">
            Row {{ f.row_number }}
          </span>
          <span class="text-[10px] font-mono text-error/90 break-all">
            {{ f.message }}
          </span>
        </div>
        }
      </div>
      } @if ((meta.omitted_failure_count ?? 0) > 0) {
      <p class="text-[10px] font-mono text-error/70">
        +{{ meta.omitted_failure_count }} additional row failure{{
          meta.omitted_failure_count === 1 ? '' : 's'
        }}
        not shown
      </p>
      }

      <!-- Download labels -->
      @if (canUseSuccessfulActions) {
      <button
        type="button"
        class="w-full btn-primary py-2 flex items-center justify-center gap-2 text-sm"
        (click)="downloadLabels()"
      >
        <sa-icon-download class="w-3.5 h-3.5" />
        <span>View Labels (PDF)</span>
      </button>
      }

      <!-- Schedule pickup CTA -->
      @if (canUseSuccessfulActions) {
      <button
        type="button"
        class="w-full btn-secondary py-2 flex items-center justify-center gap-2 text-sm card-domain-pickup border"
        (click)="schedulePickup.emit()"
      >
        Schedule Pickup
      </button>
      }
    </div>
    }
  `,
})
export class CompletionArtifactComponent {
  @Input({ required: true }) message!: ConversationMessage;
  @Output() schedulePickup = new EventEmitter<void>();
  @Output() viewLabels = new EventEmitter<string>();

  get meta(): CompletionMeta | null {
    return (this.message.metadata?.['completion'] as CompletionMeta) ?? null;
  }

  get jobId(): string | null {
    return (this.message.metadata?.['jobId'] as string) ?? null;
  }

  get allFailed(): boolean {
    return this.presentation === 'failed';
  }

  get hasFailures(): boolean {
    return this.presentation === 'partial';
  }

  get hasWarnings(): boolean {
    return this.presentation === 'warning';
  }

  get isCancelled(): boolean {
    return this.presentation === 'cancelled';
  }

  get badgeText(): string {
    if (this.isCancelled) return 'CANCELLED';
    if (this.hasWarnings) return 'COMPLETED WITH WARNINGS';
    return this.allFailed
      ? 'FAILED'
      : this.hasFailures
      ? 'PARTIAL'
      : 'COMPLETED';
  }

  get canUseSuccessfulActions(): boolean {
    const meta = this.meta;
    return (
      !!meta &&
      meta.successful > 0 &&
      (this.presentation === 'completed' ||
        this.presentation === 'warning' ||
        this.presentation === 'partial')
    );
  }

  get baseDisplay(): string {
    const displayName = this.meta?.jobName || `Command: ${this.meta?.command}`;
    const { base } = parseRefinedName(displayName);
    return base.startsWith('Command: ') ? base.slice(9) : base;
  }

  get refinements(): string[] {
    const displayName = this.meta?.jobName || `Command: ${this.meta?.command}`;
    return parseRefinedName(displayName).refinements;
  }

  get overflow(): number {
    const displayName = this.meta?.jobName || `Command: ${this.meta?.command}`;
    return parseRefinedName(displayName).overflow;
  }

  downloadLabels(): void {
    const id = this.jobId;
    if (id && this.canUseSuccessfulActions) {
      this.viewLabels.emit(id);
    }
  }

  private get presentation(): CompletionPresentation {
    const meta = this.meta;
    if (!meta) return 'completed';

    if (meta.status === 'cancelled') return 'cancelled';
    if (meta.status === 'failed') return 'failed';
    if (meta.outcome === 'failed') {
      return meta.cancelled === true ? 'cancelled' : 'failed';
    }
    if (meta.status === 'completed_with_warnings') return 'warning';
    if (meta.status === 'completed') return 'completed';
    if (meta.outcome === 'complete') {
      return meta.hasWarnings === true ? 'warning' : 'completed';
    }

    if (meta.cancelled === true) return 'cancelled';
    if (meta.hasWarnings === true) return 'warning';
    if (meta.successful === 0 && meta.failed > 0) return 'failed';
    return meta.failed > 0 ? 'partial' : 'completed';
  }
}
