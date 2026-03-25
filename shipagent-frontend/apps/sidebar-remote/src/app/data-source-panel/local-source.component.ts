/**
 * LocalSourceComponent
 *
 * Handles local file upload (CSV, Excel, JSON, XML, EDI, fixed-width)
 * and database connection. Updates DataSourceStore on success.
 * Port of local source section from React DataSourcePanel.tsx.
 */

import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  inject,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@shipagent/shared-api';
import { DataSourceStore } from '@shipagent/shared-state';
import { ConversationStore } from '@shipagent/shared-state';
import { DataSourceMappersService } from './data-source-mappers.service';
import { HardDriveIconComponent } from '@shipagent/shared-ui';
import type { DataSourceInfo } from '@shipagent/shared-types';

@Component({
  selector: 'sa-local-source',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [HardDriveIconComponent],
  template: `
    <div class="space-y-2">
      <!-- Header -->
      <div class="flex items-center gap-2">
        <sa-icon-hard-drive class="w-3.5 h-3.5 text-slate-500" />
        <span class="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Import Data Source</span>
      </div>

      <!-- Action buttons -->
      <div class="flex gap-2">
        <button
          class="flex-1 py-2 px-3 rounded-lg border border-slate-700 bg-slate-800/50 hover:bg-slate-800 hover:border-slate-600 text-slate-300 transition-colors text-xs font-medium disabled:opacity-50"
          [disabled]="isConnecting()"
          (click)="openFilePicker()"
        >
          Import File
        </button>
        <button
          [class]="dbButtonClass()"
          [disabled]="isConnecting()"
          (click)="toggleDbForm()"
        >
          Database
        </button>
      </div>
      <p class="text-[10px] text-slate-500 mt-0.5">CSV, TSV, Excel, JSON, XML, EDI, and more</p>

      <!-- Saved sources button -->
      <button
        class="w-full py-1.5 text-[11px] font-medium rounded-md border border-slate-700 bg-slate-800/50 hover:bg-slate-800 hover:border-slate-600 text-slate-300 transition-colors"
        (click)="openSavedSources.emit()"
      >
        Saved Sources
      </button>

      <!-- Database connection form -->
      @if (showDbForm()) {
        <div class="space-y-2 pt-1">
          <input
            type="text"
            [value]="dbConnectionString()"
            (input)="dbConnectionString.set($any($event.target).value)"
            placeholder="postgresql://user:pass@host:5432/db"
            class="w-full px-2.5 py-1.5 text-xs font-mono rounded bg-slate-900 border border-slate-700 text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-primary"
          />
          <button
            class="w-full btn-primary py-1.5 text-xs font-medium disabled:opacity-50"
            [disabled]="!dbConnectionString().trim() || isConnecting()"
            (click)="handleDbConnect()"
          >
            @if (isConnecting()) {
              Connecting...
            } @else {
              Connect
            }
          </button>
        </div>
      }

      <!-- Error display -->
      @if (importError()) {
        <p class="text-[10px] font-mono text-red-400 p-2 rounded bg-red-500/10">{{ importError() }}</p>
      }

      @if (isConnecting() && !importError()) {
        <p class="text-[10px] font-mono text-slate-500 text-center">Importing...</p>
      }

      <!-- Hidden file input -->
      <input
        #fileInput
        type="file"
        class="hidden"
        accept=".csv,.tsv,.txt,.ssv,.dat,.xlsx,.xls,.json,.xml,.edi,.x12,.fwf"
        (change)="handleFileSelected($event)"
      />
    </div>
  `,
})
export class LocalSourceComponent {
  private readonly apiService = inject(ApiService);
  private readonly dataSourceStore = inject(DataSourceStore);
  private readonly conversationStore = inject(ConversationStore);
  private readonly mappers = inject(DataSourceMappersService);

  readonly fileInput = viewChild.required<ElementRef<HTMLInputElement>>('fileInput');

  readonly openSavedSources = output<void>();

  readonly isConnecting = signal(false);
  readonly showDbForm = signal(false);
  readonly dbConnectionString = signal('');
  readonly importError = signal<string | null>(null);

  /** Open native file picker. */
  openFilePicker(): void {
    this.importError.set(null);
    const el = this.fileInput().nativeElement;
    el.value = '';
    el.click();
  }

  /** CSS class for the Database button — active state uses primary accent. */
  dbButtonClass(): string {
    const base = 'flex-1 py-2 px-3 rounded-lg border transition-colors text-xs font-medium disabled:opacity-50';
    if (this.showDbForm()) {
      // Active: primary border + tinted background + primary text
      return `${base} border-primary/50 bg-primary/10 text-primary`;
    }
    // Inactive: neutral
    return `${base} border-slate-700 bg-slate-800/50 text-slate-300 hover:bg-slate-800 hover:border-slate-600`;
  }

  /** Toggle database connection form visibility. */
  toggleDbForm(): void {
    this.showDbForm.update((v) => !v);
    this.importError.set(null);
  }

  /** Handle file selection from native picker — uploads to backend. */
  async handleFileSelected(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;

    const ext = (file.name.split('.').pop() ?? '').toLowerCase();
    const EXCEL_EXTS = new Set(['xlsx', 'xls']);
    const fileType: 'csv' | 'excel' = EXCEL_EXTS.has(ext) ? 'excel' : 'csv';

    this.isConnecting.set(true);
    this.importError.set(null);

    try {
      const result = await firstValueFrom(this.apiService.uploadDataSource(file));

      if (result.status === 'error') {
        this.importError.set(result.error ?? 'Import failed');
        return;
      }

      // Fixed-width files need agent-driven column setup — route to chat
      if (result.status === 'pending_agent_setup' && result.file_path) {
        this.conversationStore.setPendingMessage(
          `I uploaded ${file.name} as a fixed-width file (${result.file_path}). ` +
          `Please help me define the column layout.`,
        );
        return;
      }

      const source: DataSourceInfo = {
        type: fileType,
        status: 'connected',
        row_count: result.row_count,
        column_count: result.columns.length,
        columns: this.mappers.mapSchemaColumns(result.columns),
        connected_at: new Date().toISOString(),
        csv_path: fileType === 'csv' ? file.name : undefined,
        excel_path: fileType === 'excel' ? file.name : undefined,
      };

      this.dataSourceStore.setDataSource(source);
      this.dataSourceStore.setActiveSourceType('local');
      this.dataSourceStore.setCachedLocalConfig({ type: fileType, file_path: file.name });
    } catch (err) {
      this.importError.set(err instanceof Error ? err.message : 'Import failed');
    } finally {
      this.isConnecting.set(false);
    }
  }

  /** Connect to a database via connection string. */
  async handleDbConnect(): Promise<void> {
    if (!this.dbConnectionString().trim()) return;

    this.isConnecting.set(true);
    this.importError.set(null);

    try {
      const result = await firstValueFrom(
        this.apiService.importDataSource({
          type: 'database',
          connection_string: this.dbConnectionString().trim(),
          query: 'SELECT * FROM shipments',
        }),
      );

      if (result.status === 'error') {
        this.importError.set(result.error ?? 'Connection failed');
        return;
      }

      const source: DataSourceInfo = {
        type: 'database',
        status: 'connected',
        row_count: result.row_count,
        column_count: result.columns.length,
        columns: this.mappers.mapSchemaColumns(result.columns),
        connected_at: new Date().toISOString(),
      };

      this.dataSourceStore.setDataSource(source);
      this.dataSourceStore.setActiveSourceType('local');
      this.dataSourceStore.setCachedLocalConfig({ type: 'database' });
      this.dbConnectionString.set('');
      this.showDbForm.set(false);
    } catch (err) {
      this.importError.set(err instanceof Error ? err.message : 'Connection failed');
    } finally {
      this.isConnecting.set(false);
    }
  }
}
