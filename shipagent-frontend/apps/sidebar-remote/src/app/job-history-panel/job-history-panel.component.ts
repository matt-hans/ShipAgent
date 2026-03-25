/**
 * JobHistoryPanelComponent
 *
 * Displays shipment job history with search, status filters,
 * delete, and label reprint actions.
 * Port of React JobHistoryPanel.tsx (JobHistorySection).
 *
 * Key behavior: uses effect() watching jobStore.jobListVersion() to
 * trigger a re-fetch whenever the job list may have changed.
 */

import {
  ChangeDetectionStrategy,
  Component,
  effect,
  inject,
  OnInit,
  signal,
} from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@shipagent/shared-api';
import { JobStore } from '@shipagent/shared-state';
import {
  SearchIconComponent,
  TrashIconComponent,
  PrinterIconComponent,
  StatusBadgeComponent,
  TimeAgoPipe,
} from '@shipagent/shared-ui';
import type { BadgeStatus } from '@shipagent/shared-ui';
import type { Job, JobSummary } from '@shipagent/shared-types';

/** Derive effective display status (including 'partial'). */
function effectiveStatus(job: JobSummary): string {
  if (
    job.status === 'completed' &&
    job.successful_rows > 0 &&
    job.failed_rows > 0
  ) {
    return 'partial';
  }
  return job.status;
}

/** Map job status to StatusBadgeComponent variant. */
function statusToBadge(status: string): BadgeStatus {
  switch (status) {
    case 'completed': return 'success';
    case 'partial':   return 'warning';
    case 'running':   return 'info';
    case 'failed':    return 'error';
    case 'cancelled': return 'warning';
    case 'pending':
    default:          return 'neutral';
  }
}

const STATUS_FILTERS: string[] = ['all', 'completed', 'partial', 'failed'];

@Component({
  selector: 'sa-job-history-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    SearchIconComponent,
    TrashIconComponent,
    PrinterIconComponent,
    StatusBadgeComponent,
    TimeAgoPipe,
  ],
  template: `
    <div class="p-3 space-y-3">
      <div class="flex items-center justify-between">
        <span class="text-xs font-medium text-slate-300">Shipment History</span>
        <span class="text-[10px] font-mono text-slate-500">{{ jobs().length }} jobs</span>
      </div>

      <!-- Search -->
      <div class="relative">
        <sa-icon-search class="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
        <input
          type="text"
          [value]="search()"
          (input)="search.set($any($event.target).value)"
          placeholder="Search commands..."
          class="w-full pl-8 pr-3 py-2 text-xs font-mono rounded-md bg-slate-900 border border-slate-800 text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-primary"
        />
      </div>

      <!-- Status filters -->
      <div class="flex gap-1">
        @for (f of STATUS_FILTERS; track f) {
          <button
            class="px-2 py-1 text-[10px] font-mono rounded transition-colors"
            [class.bg-slate-700]="statusFilter() === f"
            [class.text-slate-100]="statusFilter() === f"
            [class.text-slate-500]="statusFilter() !== f"
            [class.hover:text-slate-300]="statusFilter() !== f"
            (click)="statusFilter.set(f)"
          >
            {{ f.charAt(0).toUpperCase() + f.slice(1) }}
          </button>
        }
      </div>

      <!-- Loading skeleton -->
      @if (isLoading()) {
        <div class="space-y-2">
          <div class="h-12 bg-slate-800 rounded animate-pulse"></div>
          <div class="h-12 bg-slate-800 rounded animate-pulse"></div>
          <div class="h-12 bg-slate-800 rounded animate-pulse"></div>
        </div>
      }

      <!-- Job list -->
      @if (!isLoading()) {
        <div class="space-y-1.5 max-h-[300px] overflow-y-auto">
          @if (filteredJobs().length === 0) {
            <p class="text-xs text-slate-500 text-center py-4">No jobs found</p>
          }
          @for (job of filteredJobs(); track job.id) {
            <div
              class="group relative w-full text-left p-2.5 rounded-md transition-colors cursor-pointer border"
              [class.bg-primary]="jobStore.activeJob()?.id === job.id"
              [class.bg-opacity-10]="jobStore.activeJob()?.id === job.id"
              [class.border-primary]="jobStore.activeJob()?.id === job.id"
              [class.border-opacity-30]="jobStore.activeJob()?.id === job.id"
              [class.border-transparent]="jobStore.activeJob()?.id !== job.id"
              [class.hover:bg-slate-800]="jobStore.activeJob()?.id !== job.id"
              [class.hover:bg-opacity-50]="jobStore.activeJob()?.id !== job.id"
              (click)="handleSelectJob(job)"
            >
              <div class="flex items-start justify-between gap-2">
                <div class="flex-1 min-w-0">
                  <p class="text-xs text-slate-200 line-clamp-2">
                    {{ jobDisplayName(job) }}
                  </p>
                </div>
                <div class="flex items-center gap-1.5 flex-shrink-0">
                  <sa-status-badge [status]="statusToBadge(effectiveStatus(job))">
                    <span class="text-[10px]">{{ effectiveStatus(job).toUpperCase() }}</span>
                  </sa-status-badge>

                  <!-- Reprint labels (completed jobs only) -->
                  @if (job.status === 'completed') {
                    <button
                      class="p-1 rounded opacity-0 group-hover:opacity-100 transition-opacity hover:bg-cyan-500/20 text-slate-500 hover:text-cyan-400"
                      title="Reprint labels"
                      (click)="handleReprintLabels($event, job.id)"
                    >
                      <sa-icon-printer class="w-3.5 h-3.5" />
                    </button>
                  }

                  <!-- Delete -->
                  <button
                    class="p-1 rounded opacity-0 group-hover:opacity-100 transition-opacity hover:bg-red-500/20 text-slate-500 hover:text-red-400"
                    [class.opacity-100]="deletingJobId() === job.id"
                    [class.animate-pulse]="deletingJobId() === job.id"
                    title="Delete job"
                    [disabled]="deletingJobId() === job.id"
                    (click)="handleDeleteJob($event, job.id)"
                  >
                    <sa-icon-trash class="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              <div class="flex items-center gap-2 mt-1.5">
                <span class="text-[10px] font-mono text-slate-500">{{ job.created_at | timeAgo }}</span>
                @if (job.total_rows > 0) {
                  <span class="text-slate-700">&middot;</span>
                  <span class="text-[10px] font-mono text-slate-500">
                    {{ job.successful_rows }}/{{ job.total_rows }} shipments
                  </span>
                }
              </div>
            </div>
          }
        </div>
      }
    </div>
  `,
})
export class JobHistoryPanelComponent implements OnInit {
  readonly jobStore = inject(JobStore);
  private readonly apiService = inject(ApiService);

  readonly jobs = signal<JobSummary[]>([]);
  readonly isLoading = signal(true);
  readonly search = signal('');
  readonly statusFilter = signal('all');
  readonly deletingJobId = signal<string | null>(null);

  readonly STATUS_FILTERS = STATUS_FILTERS;

  /** Expose helpers as properties for template. */
  readonly effectiveStatus = effectiveStatus;
  readonly statusToBadge = statusToBadge;

  constructor() {
    // Re-fetch jobs whenever jobListVersion changes.
    // This effect triggers on any increment from any part of the app.
    effect(() => {
      // Read the signal to subscribe
      this.jobStore.jobListVersion();
      void this.loadJobs();
    });
  }

  ngOnInit(): void {
    void this.loadJobs();
  }

  /** Display name for a job card. */
  jobDisplayName(job: JobSummary): string {
    const raw = job.name ?? '';
    if (!raw.includes(' → ')) {
      return raw.startsWith('Command: ')
        ? raw.slice(9)
        : job.original_command ?? raw ?? 'Untitled job';
    }
    return raw.split(' → ')[0] ?? raw;
  }

  /** Computed filtered job list. */
  filteredJobs(): JobSummary[] {
    const s = this.search().toLowerCase();
    const f = this.statusFilter();
    return this.jobs().filter((job) => {
      const matchesSearch = !s || (job.original_command ?? '').toLowerCase().includes(s);
      const eff = effectiveStatus(job);
      const matchesFilter = f === 'all' || eff === f;
      return matchesSearch && matchesFilter;
    });
  }

  /** Select a job and update JobStore. */
  handleSelectJob(job: JobSummary): void {
    this.jobStore.setActiveJob(job as Job);
  }

  /** Open merged labels PDF in new tab. */
  handleReprintLabels(event: MouseEvent, jobId: string): void {
    event.stopPropagation();
    window.open(this.apiService.getMergedLabelsUrl(jobId), '_blank');
  }

  /** Delete a job and remove it from local state. */
  async handleDeleteJob(event: MouseEvent, jobId: string): Promise<void> {
    event.stopPropagation();
    this.deletingJobId.set(jobId);
    try {
      await firstValueFrom(this.apiService.deleteJob(jobId));
      this.jobs.update((prev) => prev.filter((j) => j.id !== jobId));
      // Clear active job if deleted
      if (this.jobStore.activeJob()?.id === jobId) {
        this.jobStore.clearActiveJob();
      }
    } catch (err) {
      console.error('Failed to delete job:', err);
    } finally {
      this.deletingJobId.set(null);
    }
  }

  private async loadJobs(): Promise<void> {
    try {
      const data = await firstValueFrom(this.apiService.getJobs({ limit: 20 }));
      this.jobs.set(data.jobs);
    } catch (err) {
      console.error('Failed to load job history:', err);
    } finally {
      this.isLoading.set(false);
    }
  }
}
