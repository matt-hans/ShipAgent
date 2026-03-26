/**
 * JobDetailOverlayComponent — Full-screen overlay for job detail view.
 *
 * Rendered in chat-container when jobStore.activeJob() is set (i.e., when
 * a user clicks a job in the sidebar's Job History panel). Shows job header,
 * summary stats, per-row details with expand/collapse, and action buttons
 * (confirm, cancel, download labels, close).
 *
 * Port of the React JobDetailPanel.tsx logic, adapted for the chat-remote
 * module federation boundary (cannot import domain-remote directly).
 */

import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Output,
  inject,
  signal,
  OnInit,
} from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@shipagent/shared-api';
import { JobStore } from '@shipagent/shared-state';
import {
  ArrowLeftIconComponent,
  PrinterIconComponent,
  PlusIconComponent,
  CheckIconComponent,
  XCircleIconComponent,
  MapPinIconComponent,
  ChevronDownIconComponent,
  PlayIconComponent,
  XIconComponent,
  DownloadIconComponent,
} from '@shipagent/shared-ui';
import type { JobRow, OrderData, ChargeBreakdown } from '@shipagent/shared-types';

/** Format ISO date string to readable format. */
function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

/** Format currency from cents. */
function formatCurrency(cents: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
  }).format(cents / 100);
}

/** Parse order_data JSON string safely. */
function parseOrderData(raw: string | null): OrderData | null {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as OrderData;
  } catch {
    return null;
  }
}

/** Parse charge_breakdown which may be a JSON string or already an object. */
function parseChargeBreakdown(
  raw: ChargeBreakdown | string | null | undefined,
): ChargeBreakdown | null {
  if (!raw) return null;
  if (typeof raw === 'string') {
    try {
      return JSON.parse(raw) as ChargeBreakdown;
    } catch {
      return null;
    }
  }
  return raw;
}

interface RowViewModel {
  row: JobRow;
  orderData: OrderData | null;
  chargeBreakdown: ChargeBreakdown | null;
  expanded: boolean;
}

@Component({
  selector: 'app-job-detail-overlay',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ArrowLeftIconComponent,
    PrinterIconComponent,
    PlusIconComponent,
    CheckIconComponent,
    XCircleIconComponent,
    MapPinIconComponent,
    ChevronDownIconComponent,
    PlayIconComponent,
    XIconComponent,
    DownloadIconComponent,
  ],
  template: `
    @if (job()) {
      <div class="absolute inset-0 z-30 flex flex-col bg-background overflow-hidden">
        <!-- Header -->
        <div class="border-b border-slate-800 px-6 py-4">
          <div class="max-w-3xl mx-auto">
            <button
              (click)="goBack()"
              class="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 transition-colors mb-3"
            >
              <sa-icon-arrow-left class="w-3.5 h-3.5" />
              <span>Back to chat</span>
            </button>

            <div class="flex items-center justify-between gap-4">
              <div class="flex-1 min-w-0">
                <h2 class="text-lg font-medium text-slate-100 truncate">
                  {{ jobDisplayName }}
                </h2>
                <p class="text-[10px] font-mono text-slate-500 mt-1">
                  {{ formatDate(job()!.created_at) }} · Job {{ job()!.id.slice(0, 8) }}
                </p>
              </div>
              <span class="badge {{ statusBadgeClass }}">{{ job()!.status }}</span>
            </div>
          </div>
        </div>

        <!-- Content -->
        <div class="flex-1 overflow-y-auto p-6">
          <div class="max-w-3xl mx-auto space-y-6">
            <!-- Summary stats -->
            <div class="grid grid-cols-4 gap-3">
              <div class="card-premium p-3 text-center">
                <p class="text-2xl font-semibold text-slate-100">{{ job()!.total_rows }}</p>
                <p class="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Total</p>
              </div>
              <div class="card-premium p-3 text-center">
                <p class="text-2xl font-semibold text-success">{{ job()!.successful_rows }}</p>
                <p class="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Success</p>
              </div>
              <div class="card-premium p-3 text-center">
                <p class="text-2xl font-semibold text-error">{{ job()!.failed_rows }}</p>
                <p class="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Failed</p>
              </div>
              <div class="card-premium p-3 text-center">
                <p class="text-2xl font-semibold text-amber-400">
                  {{ formatCost(displayCostCents()) }}
                </p>
                <p class="text-[10px] font-mono text-slate-500 uppercase tracking-wider">
                  {{ job()!.status === 'pending' ? 'Est. Cost' : 'Cost' }}
                </p>
              </div>
            </div>

            <!-- Error info if job failed -->
            @if (job()!.error_code) {
              <div class="p-3 rounded-lg bg-error/10 border border-error/30">
                <p class="text-xs font-mono text-error">
                  {{ job()!.error_code }}: {{ job()!.error_message }}
                </p>
              </div>
            }

            <!-- Action error -->
            @if (actionError()) {
              <div class="p-3 rounded-lg bg-error/10 border border-error/30">
                <p class="text-xs text-error">{{ actionError() }}</p>
              </div>
            }

            <!-- Action buttons -->
            <div class="flex gap-3 flex-wrap">
              <!-- Pending: Confirm & Cancel -->
              @if (job()!.status === 'pending') {
                <button
                  (click)="handleConfirm()"
                  [disabled]="isConfirming()"
                  class="btn-primary py-2.5 px-4 flex items-center gap-2"
                >
                  @if (isConfirming()) {
                    <span class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
                    <span>Confirming...</span>
                  } @else {
                    <sa-icon-play class="w-4 h-4" />
                    <span>Confirm &amp; Execute</span>
                  }
                </button>
                <button
                  (click)="handleCancel()"
                  [disabled]="isConfirming() || isCancelling()"
                  class="btn-secondary py-2.5 px-4 flex items-center gap-2"
                >
                  @if (isCancelling()) {
                    <span class="w-4 h-4 border-2 border-slate-500/30 border-t-slate-500 rounded-full animate-spin"></span>
                    <span>Cancelling...</span>
                  } @else {
                    <sa-icon-x class="w-4 h-4" />
                    <span>Cancel</span>
                  }
                </button>
              }

              <!-- Completed: View Labels + Download -->
              @if (job()!.status === 'completed') {
                <a
                  [href]="mergedLabelsUrl()"
                  target="_blank"
                  class="btn-primary py-2.5 px-4 flex items-center gap-2"
                >
                  <sa-icon-printer class="w-4 h-4" />
                  <span>Download Labels (PDF)</span>
                </a>
                <a
                  [href]="zipLabelsUrl()"
                  target="_blank"
                  class="btn-secondary py-2.5 px-4 flex items-center gap-2"
                >
                  <sa-icon-download class="w-4 h-4" />
                  <span>Download Labels (ZIP)</span>
                </a>
                <button
                  (click)="viewLabels.emit(job()!.id)"
                  class="btn-secondary py-2.5 px-4 flex items-center gap-2"
                >
                  <sa-icon-printer class="w-4 h-4" />
                  <span>Preview Labels</span>
                </button>
              }

              <!-- Cancelled info -->
              @if (job()!.status === 'cancelled') {
                <p class="text-xs text-slate-500 py-2.5">This batch was cancelled.</p>
              }

              <!-- Close button (always visible) -->
              <button
                (click)="goBack()"
                class="btn-secondary py-2.5 px-4 flex items-center gap-2 ml-auto"
              >
                <sa-icon-plus class="w-4 h-4 rotate-45" />
                <span>Close</span>
              </button>
            </div>

            <!-- Row details -->
            <div class="space-y-2">
              <div class="flex items-center justify-between">
                <p class="text-[10px] font-mono text-slate-500 uppercase tracking-wider">
                  Shipments
                </p>
                <p class="text-[10px] font-mono text-slate-500">
                  {{ rowViewModels().length }} shipments
                </p>
              </div>

              @if (isLoading()) {
                <div class="space-y-2">
                  <div class="h-10 bg-slate-800 rounded shimmer"></div>
                  <div class="h-10 bg-slate-800 rounded shimmer"></div>
                  <div class="h-10 bg-slate-800 rounded shimmer"></div>
                </div>
              } @else if (rowViewModels().length === 0) {
                <p class="text-xs text-slate-500 text-center py-8">No shipments found</p>
              } @else {
                <div class="rounded-md border border-slate-800 overflow-hidden">
                  @for (vm of rowViewModels(); track vm.row.id; let i = $index) {
                    <div class="border-b border-slate-800 last:border-0">
                      <!-- Row header -->
                      <button
                        (click)="vm.orderData ? toggleRow(i) : null"
                        class="w-full flex items-center justify-between px-3 py-2.5 text-xs transition-colors"
                        [class.hover:bg-slate-800/30]="vm.orderData"
                        [class.cursor-pointer]="vm.orderData"
                        [class.cursor-default]="!vm.orderData"
                        [class.bg-slate-800/20]="vm.expanded"
                      >
                        <div class="flex items-center gap-3 flex-1 min-w-0">
                          <!-- Status icon -->
                          @if (vm.row.status === 'completed') {
                            <sa-icon-check class="w-3.5 h-3.5 text-success flex-shrink-0" />
                          } @else if (vm.row.status === 'failed') {
                            <sa-icon-x-circle class="w-3.5 h-3.5 text-error flex-shrink-0" />
                          } @else {
                            <span class="w-3.5 h-3.5 rounded-full border border-slate-600 flex-shrink-0"></span>
                          }

                          @if (vm.orderData) {
                            <sa-icon-chevron-down
                              class="w-3 h-3 text-slate-500 transition-transform flex-shrink-0"
                              [class.rotate-180]="vm.expanded"
                            />
                          }

                          <div class="flex-1 min-w-0 text-left">
                            <span class="text-slate-300 font-mono text-[10px]">Row {{ vm.row.row_number }}</span>
                            @if (vm.orderData) {
                              <span class="text-slate-200 ml-2 font-medium truncate">
                                {{ vm.orderData.ship_to_name }}
                              </span>
                            }
                          </div>
                        </div>

                        <div class="flex items-center gap-3 flex-shrink-0">
                          @if (vm.row.destination_country && vm.row.destination_country !== 'US') {
                            <span class="px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400 text-[8px] font-mono font-medium uppercase">
                              {{ vm.row.destination_country }}
                            </span>
                          }
                          @if (vm.row.tracking_number) {
                            <span class="font-mono text-cyan-400 text-[10px]">{{ vm.row.tracking_number }}</span>
                          }
                          @if ((vm.row.cost_cents ?? 0) > 0) {
                            <span class="font-mono text-amber-400 text-[10px]">{{ formatCost(vm.row.cost_cents!) }}</span>
                          }
                          @if (vm.row.status === 'failed' && vm.row.error_message) {
                            <span
                              class="text-error text-[10px] truncate max-w-[120px]"
                              [title]="vm.row.error_message"
                            >
                              {{ vm.row.error_code || 'Error' }}
                            </span>
                          }
                        </div>
                      </button>

                      <!-- Expanded order details -->
                      @if (vm.expanded && vm.orderData) {
                        <div class="px-4 py-3 bg-slate-800/30 border-t border-slate-800 animate-fade-in">
                          <div class="grid grid-cols-2 gap-4">
                            <div class="space-y-1">
                              <span class="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Recipient</span>
                              <p class="text-sm text-slate-200">{{ vm.orderData.ship_to_name }}</p>
                              @if (vm.orderData.ship_to_company) {
                                <p class="text-xs text-slate-400">{{ vm.orderData.ship_to_company }}</p>
                              }
                            </div>
                            <div class="space-y-1">
                              <span class="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Customer</span>
                              <p class="text-sm text-slate-200">{{ vm.orderData.customer_name || vm.orderData.ship_to_name }}</p>
                              @if (vm.orderData.customer_email) {
                                <p class="text-[10px] font-mono text-slate-500">{{ vm.orderData.customer_email }}</p>
                              }
                            </div>
                          </div>

                          <div class="mt-3 pt-3 border-t border-slate-800/50">
                            <div class="flex items-center gap-1.5 text-[10px] font-mono text-slate-500 uppercase tracking-wider mb-1">
                              <sa-icon-map-pin class="w-3 h-3" />
                              <span>Address</span>
                            </div>
                            <p class="text-sm text-slate-200">{{ vm.orderData.ship_to_address1 }}</p>
                            @if (vm.orderData.ship_to_address2) {
                              <p class="text-sm text-slate-300">{{ vm.orderData.ship_to_address2 }}</p>
                            }
                            <p class="text-sm text-slate-300">
                              {{ vm.orderData.ship_to_city }}, {{ vm.orderData.ship_to_state }} {{ vm.orderData.ship_to_postal_code }}
                            </p>
                          </div>

                          <!-- Charge breakdown for international rows -->
                          @if (vm.chargeBreakdown) {
                            <div class="mt-3 pt-3 border-t border-slate-800/50">
                              <span class="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Charge Breakdown</span>
                              <div class="mt-1 space-y-0.5">
                                @if (vm.chargeBreakdown.transportationCharges) {
                                  <div class="flex justify-between text-[10px] font-mono text-slate-400">
                                    <span>Transportation</span>
                                    <span>\${{ vm.chargeBreakdown.transportationCharges.monetaryValue }}</span>
                                  </div>
                                }
                                @if (vm.chargeBreakdown.dutiesAndTaxes) {
                                  <div class="flex justify-between text-[10px] font-mono text-amber-400/80">
                                    <span>Duties &amp; Taxes</span>
                                    <span>\${{ vm.chargeBreakdown.dutiesAndTaxes.monetaryValue }}</span>
                                  </div>
                                }
                                @if (vm.chargeBreakdown.brokerageCharges) {
                                  <div class="flex justify-between text-[10px] font-mono text-slate-400">
                                    <span>Brokerage</span>
                                    <span>\${{ vm.chargeBreakdown.brokerageCharges.monetaryValue }}</span>
                                  </div>
                                }
                              </div>
                            </div>
                          }

                          @if (vm.orderData.order_number || vm.orderData.order_id) {
                            <div class="mt-2 text-[10px] font-mono text-slate-500">
                              Order #{{ vm.orderData.order_number || vm.orderData.order_id }}
                            </div>
                          }
                        </div>
                      }
                    </div>
                  }
                </div>
              }
            </div>
          </div>
        </div>
      </div>
    }
  `,
})
export class JobDetailOverlayComponent implements OnInit {
  private readonly apiService = inject(ApiService);
  private readonly jobStore = inject(JobStore);

  /** Emitted when user clicks "Preview Labels" to open the label modal. */
  @Output() viewLabels = new EventEmitter<string>();

  readonly job = this.jobStore.activeJob;
  readonly isLoading = signal(true);
  readonly isConfirming = signal(false);
  readonly isCancelling = signal(false);
  readonly actionError = signal<string | null>(null);
  readonly rows = signal<JobRow[]>([]);
  readonly rowViewModels = signal<RowViewModel[]>([]);

  protected formatDate = formatDate;
  protected formatCost = formatCurrency;

  ngOnInit(): void {
    const j = this.job();
    if (j) {
      this.loadJobRows(j.id);
    }
  }

  private async loadJobRows(jobId: string): Promise<void> {
    this.isLoading.set(true);
    try {
      const rows = await firstValueFrom(this.apiService.getJobRows(jobId));
      this.rows.set(rows);
      this.rowViewModels.set(
        rows.map((row) => ({
          row,
          orderData: parseOrderData(row.order_data),
          chargeBreakdown: parseChargeBreakdown(row.charge_breakdown),
          expanded: false,
        })),
      );
    } catch (err) {
      console.error('Failed to load job rows:', err);
    } finally {
      this.isLoading.set(false);
    }
  }

  /** Toggle expand/collapse for a row. */
  toggleRow(index: number): void {
    this.rowViewModels.update((vms) =>
      vms.map((vm, i) =>
        i === index ? { ...vm, expanded: !vm.expanded } : vm,
      ),
    );
  }

  /** Derive display name for the job header. */
  get jobDisplayName(): string {
    const j = this.job();
    if (!j) return '';
    if (j.name?.startsWith('Command: ')) return j.name.slice(9);
    return j.original_command || j.name || '';
  }

  /** Derive badge class for the current job status. */
  get statusBadgeClass(): string {
    const status = this.job()?.status ?? '';
    const map: Record<string, string> = {
      completed: 'badge-success',
      running: 'badge-info',
      failed: 'badge-error',
      pending: 'badge-neutral',
      cancelled: 'badge-warning',
    };
    return map[status] ?? 'badge-neutral';
  }

  /** Compute display cost in cents. */
  displayCostCents(): number {
    const j = this.job();
    if (!j) return 0;
    return (
      j.total_cost_cents ||
      this.rows().reduce((sum, r) => sum + (r.cost_cents ?? 0), 0)
    );
  }

  /** Build merged labels PDF URL. */
  mergedLabelsUrl(): string {
    const j = this.job();
    return j ? this.apiService.getMergedLabelsUrl(j.id) : '';
  }

  /** Build ZIP labels URL. */
  zipLabelsUrl(): string {
    const j = this.job();
    return j ? this.apiService.getZipLabelsUrl(j.id) : '';
  }

  /** Confirm and execute the pending batch. */
  async handleConfirm(): Promise<void> {
    const j = this.job();
    if (!j) return;
    this.isConfirming.set(true);
    this.actionError.set(null);
    try {
      await firstValueFrom(this.apiService.confirmJob(j.id));
      this.jobStore.incrementJobListVersion();
      // Reload the job to get updated status.
      const updated = await firstValueFrom(this.apiService.getJob(j.id));
      this.jobStore.setActiveJob(updated);
      void this.loadJobRows(j.id);
    } catch (err) {
      this.actionError.set(
        err instanceof Error ? err.message : 'Failed to confirm batch',
      );
    } finally {
      this.isConfirming.set(false);
    }
  }

  /** Cancel the pending batch. */
  async handleCancel(): Promise<void> {
    const j = this.job();
    if (!j) return;
    this.isCancelling.set(true);
    this.actionError.set(null);
    try {
      await firstValueFrom(this.apiService.cancelJob(j.id));
      this.jobStore.incrementJobListVersion();
      // Reload to get updated status.
      const updated = await firstValueFrom(this.apiService.getJob(j.id));
      this.jobStore.setActiveJob(updated);
    } catch (err) {
      this.actionError.set(
        err instanceof Error ? err.message : 'Failed to cancel batch',
      );
    } finally {
      this.isCancelling.set(false);
    }
  }

  /** Close the overlay and return to chat. */
  goBack(): void {
    this.jobStore.clearActiveJob();
  }
}
