/**
 * ProgressDisplayComponent — Real-time batch execution progress display.
 *
 * Reads live progress signals from JobProgressSseService.
 * Shows progress bar, stats grid, per-row failure details, and a
 * download button when complete. Matches React's ProgressDisplay component.
 */

import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  OnChanges,
  OnDestroy,
  OnInit,
  Output,
  SimpleChanges,
  inject,
  effect,
  Injector,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormatCurrencyPipe, DownloadIconComponent } from '@shipagent/shared-ui';
import { JobProgressSseService } from '../../services/job-progress-sse.service';

@Component({
  selector: 'app-progress-display',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormatCurrencyPipe, DownloadIconComponent],
  template: `
    <div class="card-premium p-4 space-y-4"
      [class.scan-line]="progressService.isRunning()"
      [class.border-success/30]="progressService.isComplete()"
      [class.border-error/30]="progressService.isFailed()"
    >
      <!-- Header -->
      <div class="flex items-center justify-between">
        <h3 class="text-sm font-medium text-slate-200">
          @if (progressService.isComplete()) {
            Batch Complete
          } @else if (progressService.isFailed()) {
            Batch Failed
          } @else {
            Processing Shipments
          }
        </h3>
        <span class="badge"
          [class.badge-success]="progressService.isComplete()"
          [class.badge-error]="progressService.isFailed()"
          [class.badge-info]="progressService.isRunning()"
        >
          {{ progressService.progress().status }}
        </span>
      </div>

      <!-- Progress bar -->
      <div class="space-y-2">
        <div class="progress-bar">
          <div
            class="progress-bar-fill"
            [class.animated]="progressService.isRunning()"
            [style.width.%]="progressService.percentage()"
          ></div>
        </div>
        <div class="flex justify-between text-xs font-mono">
          <span class="text-slate-400">
            {{ progressService.progress().processed }} / {{ progressService.progress().total }} shipments
          </span>
          <span class="text-slate-400">{{ progressService.percentage() }}%</span>
        </div>
      </div>

      <!-- Stats grid -->
      <div class="grid gap-2"
        [class.grid-cols-4]="!progressService.progress().dutiesTaxesCents"
        [class.grid-cols-5]="progressService.progress().dutiesTaxesCents"
      >
        <div class="p-2 rounded bg-slate-800/50 text-center">
          <p class="text-lg font-semibold text-slate-100">{{ progressService.progress().total }}</p>
          <p class="text-[10px] font-mono text-slate-500">Total</p>
        </div>
        <div class="p-2 rounded bg-slate-800/50 text-center">
          <p class="text-lg font-semibold text-success">{{ progressService.progress().successful }}</p>
          <p class="text-[10px] font-mono text-slate-500">Success</p>
        </div>
        <div class="p-2 rounded bg-slate-800/50 text-center">
          <p class="text-lg font-semibold text-error">{{ progressService.progress().failed }}</p>
          <p class="text-[10px] font-mono text-slate-500">Failed</p>
        </div>
        <div class="p-2 rounded bg-slate-800/50 text-center">
          <p class="text-lg font-semibold text-primary">
            {{ progressService.progress().totalCostCents | formatCurrency }}
          </p>
          <p class="text-[10px] font-mono text-slate-500">Cost</p>
        </div>
        @if ((progressService.progress().dutiesTaxesCents ?? 0) > 0) {
          <div class="p-2 rounded bg-amber-500/10 border border-amber-500/20 text-center">
            <p class="text-lg font-semibold text-amber-400">
              {{ progressService.progress().dutiesTaxesCents! | formatCurrency }}
            </p>
            <p class="text-[10px] font-mono text-amber-400/70">Duties</p>
          </div>
        }
      </div>

      <!-- Per-row failure details -->
      @if (progressService.progress().rowFailures.length > 0) {
        <div class="space-y-1.5">
          <p class="text-[11px] font-medium text-error/90">
            {{ progressService.progress().rowFailures.length }} row{{ progressService.progress().rowFailures.length !== 1 ? 's' : '' }} failed:
          </p>
          <div class="max-h-[120px] overflow-y-auto space-y-1">
            @for (failure of progressService.progress().rowFailures; track failure.rowNumber) {
              <div class="p-2 rounded bg-error/10 border border-error/20 flex items-start gap-2">
                <span class="text-[10px] font-mono text-error/70 flex-shrink-0 mt-px">
                  Row {{ failure.rowNumber }}
                </span>
                <span class="text-[10px] font-mono text-error/90 break-all">
                  {{ failure.errorMessage }}
                </span>
              </div>
            }
          </div>
        </div>
      }

      <!-- Batch-level error (when no per-row details) -->
      @if (progressService.isFailed() && progressService.progress().error && progressService.progress().rowFailures.length === 0) {
        <div class="p-3 rounded-lg bg-error/10 border border-error/30">
          <p class="text-xs font-mono text-error">
            {{ progressService.progress().error!.code }}: {{ progressService.progress().error!.message }}
          </p>
        </div>
      }

      <!-- Download button when complete -->
      @if (progressService.isComplete() && jobId) {
        <button
          type="button"
          class="w-full btn-primary py-2.5 flex items-center justify-center gap-2"
          (click)="downloadLabels()"
        >
          <sa-icon-download class="w-4 h-4" />
          <span>Download All Labels (PDF)</span>
        </button>
      }
    </div>
  `,
})
export class ProgressDisplayComponent implements OnInit, OnChanges, OnDestroy {
  @Input({ required: true }) jobId!: string;
  @Output() complete = new EventEmitter<void>();
  @Output() failed = new EventEmitter<void>();
  @Output() viewLabels = new EventEmitter<string>();

  readonly progressService = inject(JobProgressSseService);
  private readonly injector = inject(Injector);

  private completeFired = false;
  private failFired = false;

  ngOnInit(): void {
    this.connectToJob();
    this.setupCompletionEffects();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['jobId'] && !changes['jobId'].isFirstChange()) {
      this.completeFired = false;
      this.failFired = false;
      this.connectToJob();
    }
  }

  ngOnDestroy(): void {
    this.progressService.disconnect();
  }

  downloadLabels(): void {
    if (this.jobId) {
      this.viewLabels.emit(this.jobId);
    }
  }

  private connectToJob(): void {
    if (this.jobId) {
      this.progressService.connectToJobProgress(this.jobId);
    }
  }

  private setupCompletionEffects(): void {
    effect(() => {
      if (this.progressService.isComplete() && !this.completeFired) {
        this.completeFired = true;
        this.complete.emit();
      }
    }, { injector: this.injector });

    effect(() => {
      if (this.progressService.isFailed() && !this.failFired) {
        this.failFired = true;
        this.failed.emit();
      }
    }, { injector: this.injector });
  }
}
