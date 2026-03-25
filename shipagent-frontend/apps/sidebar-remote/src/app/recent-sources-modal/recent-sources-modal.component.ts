/**
 * RecentSourcesModalComponent
 *
 * Modal for browsing and reconnecting previously used data sources.
 * Features search, type filtering, reconnect, individual and bulk delete.
 * Port of React RecentSourcesModal.tsx.
 */

import {
  ChangeDetectionStrategy,
  Component,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@shipagent/shared-api';
import {
  SearchIconComponent,
  FileIconComponent,
  DatabaseIconComponent,
  TrashIconComponent,
  XIconComponent,
} from '@shipagent/shared-ui';
import { TimeAgoPipe } from '@shipagent/shared-ui';
import type { DataSourceInfo, SavedDataSource } from '@shipagent/shared-types';

const TYPE_LABELS: Record<string, string> = {
  fixed_width: 'Fixed Width',
  edi: 'EDI',
};

function typeLabel(type: string): string {
  return TYPE_LABELS[type] ?? (type.charAt(0).toUpperCase() + type.slice(1));
}

@Component({
  selector: 'sa-recent-sources-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    SearchIconComponent,
    FileIconComponent,
    DatabaseIconComponent,
    TrashIconComponent,
    XIconComponent,
    TimeAgoPipe,
  ],
  template: `
    @if (open()) {
      <!-- Modal overlay -->
      <div class="fixed inset-0 z-50 flex items-center justify-center">
        <!-- Backdrop -->
        <div class="absolute inset-0 bg-black/60 backdrop-blur-sm" (click)="closed.emit()"></div>

        <!-- Modal panel -->
        <div class="relative w-full max-w-lg mx-4 rounded-xl border border-slate-700 bg-slate-950 shadow-2xl flex flex-col max-h-[80vh]">
          <!-- Header -->
          <div class="flex items-center justify-between px-5 py-4 border-b border-slate-800">
            <h2 class="text-sm font-semibold text-slate-100">Recent Data Sources</h2>
            <button
              class="p-1 rounded hover:bg-slate-800 text-slate-500 hover:text-slate-300 transition-colors"
              (click)="closed.emit()"
            >
              <sa-icon-x class="w-4 h-4" />
            </button>
          </div>

          <!-- Search + filters -->
          <div class="px-5 pt-4 pb-2 space-y-3">
            <div class="relative">
              <sa-icon-search class="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
              <input
                type="text"
                [value]="search()"
                (input)="search.set($any($event.target).value)"
                placeholder="Search sources..."
                class="w-full pl-8 pr-3 py-2 text-xs font-mono rounded-md bg-slate-800/50 border border-slate-700 text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-primary"
              />
            </div>
            <div class="flex gap-1.5 flex-wrap">
              @for (t of TYPE_FILTERS; track t) {
                <button
                  class="px-2.5 py-1 text-[10px] font-mono rounded-full transition-colors"
                  [class.bg-primary]="typeFilter() === t"
                  [class.bg-opacity-20]="typeFilter() === t"
                  [class.text-primary]="typeFilter() === t"
                  [class.border]="true"
                  [class.border-primary]="typeFilter() === t"
                  [class.border-opacity-30]="typeFilter() === t"
                  [class.border-transparent]="typeFilter() !== t"
                  [class.text-slate-500]="typeFilter() !== t"
                  [class.hover:text-slate-300]="typeFilter() !== t"
                  (click)="typeFilter.set(t)"
                >
                  {{ t === 'all' ? 'All' : typeLabel(t) }}
                </button>
              }
            </div>
          </div>

          <!-- Source list -->
          <div class="flex-1 overflow-y-auto px-5 py-2 min-h-0">
            @if (isLoading()) {
              <div class="space-y-2 py-4">
                @for (i of [1,2,3]; track i) {
                  <div class="h-14 bg-slate-800 rounded-lg animate-pulse"></div>
                }
              </div>
            } @else if (filteredSources().length === 0) {
              <div class="flex flex-col items-center justify-center py-12 text-slate-500">
                <sa-icon-database class="w-8 h-8 mb-3 opacity-40" />
                <p class="text-xs">
                  {{ sources().length === 0 ? 'No saved sources yet' : 'No sources match filters' }}
                </p>
                <p class="text-[10px] mt-1 text-slate-600">
                  {{ sources().length === 0 ? 'Connect a data source and it will appear here' : 'Try a different search or filter' }}
                </p>
              </div>
            } @else {
              <div class="space-y-1.5">
                @for (source of filteredSources(); track source.id) {
                  <div
                    class="group flex items-center gap-3 p-3 rounded-lg border transition-colors"
                    [class.border-primary]="selected().has(source.id)"
                    [class.border-opacity-30]="selected().has(source.id)"
                    [class.bg-primary]="selected().has(source.id)"
                    [class.bg-opacity-5]="selected().has(source.id)"
                    [class.border-transparent]="!selected().has(source.id)"
                    [class.hover:bg-slate-800]="!selected().has(source.id)"
                    [class.hover:bg-opacity-50]="!selected().has(source.id)"
                  >
                    <!-- Checkbox -->
                    <input
                      type="checkbox"
                      class="w-3.5 h-3.5 rounded border-slate-600 bg-slate-800 text-primary focus:ring-0 focus:ring-offset-0 cursor-pointer flex-shrink-0"
                      [checked]="selected().has(source.id)"
                      (change)="toggleSelect(source.id)"
                    />

                    <!-- Icon -->
                    <div class="flex-shrink-0">
                      @if (source.source_type === 'database') {
                        <sa-icon-database class="w-4 h-4 text-amber-400" />
                      } @else {
                        <sa-icon-file class="w-4 h-4" [class]="fileIconClass(source.source_type)" />
                      }
                    </div>

                    <!-- Info -->
                    <div class="flex-1 min-w-0">
                      <p class="text-xs font-medium text-slate-200 truncate">{{ source.name }}</p>
                      <div class="flex items-center gap-2 mt-0.5">
                        <span class="text-[10px] font-mono text-slate-500">{{ source.row_count.toLocaleString() }} rows</span>
                        <span class="text-slate-700">&middot;</span>
                        <span class="text-[10px] font-mono text-slate-500">{{ source.last_used_at | timeAgo }}</span>
                        <span class="text-slate-700">&middot;</span>
                        <span class="text-[9px] font-mono uppercase" [class]="typeColorClass(source.source_type)">
                          {{ typeLabel(source.source_type) }}
                        </span>
                      </div>
                    </div>

                    <!-- Actions -->
                    <div class="flex items-center gap-1.5 flex-shrink-0">
                      <button
                        class="px-3 py-1.5 text-[10px] font-medium rounded-md bg-primary/10 text-primary hover:bg-primary/20 border border-primary/20 transition-colors disabled:opacity-50"
                        [disabled]="reconnectingId() === source.id"
                        (click)="handleReconnect(source)"
                      >
                        @if (reconnectingId() === source.id) {
                          Connecting...
                        } @else if (source.source_type === 'database') {
                          Connect
                        } @else {
                          Reconnect
                        }
                      </button>
                      <button
                        class="p-1.5 rounded opacity-0 group-hover:opacity-100 hover:bg-red-500/20 text-slate-500 hover:text-red-400 transition-all"
                        title="Delete"
                        (click)="handleDelete(source.id)"
                      >
                        <sa-icon-trash class="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                }
              </div>
            }
          </div>

          <!-- DB connection string input (shown when a DB source is pending) -->
          @if (dbSourceId()) {
            <div class="px-5 py-3 border-t border-slate-800">
              <p class="text-[10px] font-mono text-slate-500 mb-2">
                Enter connection string for {{ dbSourceName() }}
              </p>
              <div class="flex gap-2">
                <input
                  type="text"
                  [value]="dbConnStr()"
                  (input)="dbConnStr.set($any($event.target).value)"
                  (keydown.enter)="handleDbReconnect()"
                  placeholder="postgresql://user:pass@host:5432/db"
                  class="flex-1 px-2.5 py-1.5 text-xs font-mono rounded bg-slate-800/50 border border-slate-700 text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-primary"
                />
                <button
                  class="px-4 py-1.5 text-xs font-medium rounded btn-primary disabled:opacity-50"
                  [disabled]="!dbConnStr().trim() || reconnectingId() === dbSourceId()"
                  (click)="handleDbReconnect()"
                >
                  @if (reconnectingId() === dbSourceId()) { Connecting... } @else { Connect }
                </button>
              </div>
            </div>
          }

          <!-- Error -->
          @if (error()) {
            <div class="px-5 py-2">
              <p class="text-[10px] font-mono text-red-400 p-2 rounded bg-red-500/10">{{ error() }}</p>
            </div>
          }

          <!-- Footer -->
          <div class="flex items-center justify-between px-5 py-3 border-t border-slate-800">
            <div class="flex items-center gap-3">
              <label class="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  class="w-3.5 h-3.5 rounded border-slate-600 bg-slate-800 text-primary focus:ring-0 focus:ring-offset-0 cursor-pointer"
                  [disabled]="filteredSources().length === 0"
                  [checked]="filteredSources().length > 0 && selected().size === filteredSources().length"
                  (change)="toggleSelectAll()"
                />
                <span class="text-[10px] font-mono text-slate-500">Select all</span>
              </label>
              @if (selected().size > 0) {
                <button
                  class="text-[10px] font-medium text-red-400 hover:underline"
                  (click)="handleBulkDelete()"
                >
                  Delete {{ selected().size }}
                </button>
              }
            </div>
            <button
              class="px-4 py-1.5 text-xs font-medium rounded border border-slate-700 text-slate-400 hover:text-slate-200 hover:border-slate-600 transition-colors"
              (click)="closed.emit()"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    }
  `,
})
export class RecentSourcesModalComponent {
  private readonly apiService = inject(ApiService);

  readonly open = input.required<boolean>();
  readonly closed = output<void>();
  readonly reconnected = output<DataSourceInfo>();

  readonly sources = signal<SavedDataSource[]>([]);
  readonly isLoading = signal(false);
  readonly search = signal('');
  readonly typeFilter = signal('all');
  readonly selected = signal<Set<string>>(new Set());
  readonly reconnectingId = signal<string | null>(null);
  readonly dbConnStr = signal('');
  readonly dbSourceId = signal<string | null>(null);
  readonly error = signal<string | null>(null);

  readonly TYPE_FILTERS = ['all', 'csv', 'excel', 'json', 'xml', 'fixed_width', 'edi', 'database'];

  /** Expose helper as method for template use. */
  readonly typeLabel = typeLabel;

  constructor() {
    // Reload sources when modal opens
    effect(() => {
      if (this.open()) {
        this.isLoading.set(true);
        this.error.set(null);
        this.selected.set(new Set());
        this.dbSourceId.set(null);
        this.dbConnStr.set('');
        this.loadSources();
      }
    });
  }

  /** Derived filtered list of sources. */
  filteredSources(): SavedDataSource[] {
    const s = this.search().toLowerCase();
    const t = this.typeFilter();
    return this.sources().filter((src) => {
      const matchesSearch = !s || src.name.toLowerCase().includes(s);
      const matchesType = t === 'all' || src.source_type === t;
      return matchesSearch && matchesType;
    });
  }

  /** Display name for db source awaiting connection string. */
  dbSourceName(): string {
    return this.sources().find((s) => s.id === this.dbSourceId())?.name ?? '';
  }

  /** CSS class for file icon colour by type. */
  fileIconClass(type: string): string {
    switch (type) {
      case 'json': return 'text-yellow-400';
      case 'xml': return 'text-orange-400';
      case 'edi': return 'text-purple-400';
      case 'fixed_width': return 'text-teal-400';
      case 'excel': return 'text-green-400';
      default: return 'text-cyan-400';
    }
  }

  /** CSS class for type label colour. */
  typeColorClass(type: string): string {
    switch (type) {
      case 'csv': return 'text-cyan-500';
      case 'excel': return 'text-green-500';
      case 'json': return 'text-yellow-500';
      case 'xml': return 'text-orange-500';
      case 'edi': return 'text-purple-500';
      case 'fixed_width': return 'text-teal-500';
      default: return 'text-amber-500';
    }
  }

  toggleSelect(id: string): void {
    const next = new Set(this.selected());
    if (next.has(id)) next.delete(id); else next.add(id);
    this.selected.set(next);
  }

  toggleSelectAll(): void {
    const filtered = this.filteredSources();
    if (this.selected().size === filtered.length) {
      this.selected.set(new Set());
    } else {
      this.selected.set(new Set(filtered.map((s) => s.id)));
    }
  }

  async handleReconnect(source: SavedDataSource): Promise<void> {
    if (source.source_type === 'database') {
      this.dbSourceId.set(source.id);
      this.dbConnStr.set('');
      return;
    }

    this.reconnectingId.set(source.id);
    this.error.set(null);
    try {
      const result = await firstValueFrom(this.apiService.reconnectSavedSource(source.id));
      const info: DataSourceInfo = {
        type: source.source_type,
        status: 'connected',
        row_count: result.row_count,
        column_count: result.column_count,
        connected_at: new Date().toISOString(),
        csv_path: source.source_type === 'csv' ? (source.file_path ?? undefined) : undefined,
        excel_path: source.source_type === 'excel' ? (source.file_path ?? undefined) : undefined,
        excel_sheet: source.sheet_name ?? undefined,
        file_path: source.file_path ?? undefined,
      };
      this.reconnected.emit(info);
      this.closed.emit();
    } catch (err) {
      this.error.set(err instanceof Error ? err.message : 'Reconnect failed');
    } finally {
      this.reconnectingId.set(null);
    }
  }

  async handleDbReconnect(): Promise<void> {
    const sourceId = this.dbSourceId();
    if (!sourceId || !this.dbConnStr().trim()) return;

    this.reconnectingId.set(sourceId);
    this.error.set(null);
    try {
      const source = this.sources().find((s) => s.id === sourceId);
      const result = await firstValueFrom(
        this.apiService.reconnectSavedSource(sourceId, this.dbConnStr().trim()),
      );
      const info: DataSourceInfo = {
        type: 'database',
        status: 'connected',
        row_count: result.row_count,
        column_count: result.column_count,
        connected_at: new Date().toISOString(),
        database_query: source?.db_query ?? undefined,
      };
      this.reconnected.emit(info);
      this.closed.emit();
    } catch (err) {
      this.error.set(err instanceof Error ? err.message : 'Reconnect failed');
    } finally {
      this.reconnectingId.set(null);
    }
  }

  async handleDelete(id: string): Promise<void> {
    try {
      await firstValueFrom(this.apiService.deleteSavedSource(id));
      this.sources.update((prev) => prev.filter((s) => s.id !== id));
      const next = new Set(this.selected());
      next.delete(id);
      this.selected.set(next);
      if (this.dbSourceId() === id) {
        this.dbSourceId.set(null);
        this.dbConnStr.set('');
      }
    } catch (err) {
      this.error.set(err instanceof Error ? err.message : 'Delete failed');
    }
  }

  async handleBulkDelete(): Promise<void> {
    const ids = Array.from(this.selected());
    if (ids.length === 0) return;
    try {
      await firstValueFrom(this.apiService.bulkDeleteSavedSources(ids));
      const selectedSet = this.selected();
      this.sources.update((prev) => prev.filter((s) => !selectedSet.has(s.id)));
      this.selected.set(new Set());
    } catch (err) {
      this.error.set(err instanceof Error ? err.message : 'Bulk delete failed');
    }
  }

  private async loadSources(): Promise<void> {
    try {
      const res = await firstValueFrom(this.apiService.getSavedSources());
      this.sources.set(res.sources);
    } catch (err) {
      this.error.set(err instanceof Error ? err.message : 'Failed to load sources');
    } finally {
      this.isLoading.set(false);
    }
  }
}
