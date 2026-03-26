/**
 * DataSourcePanelComponent
 *
 * Main data source management panel for the sidebar.
 * Shows the connected data source status, local source controls,
 * platform source controls, write-back toggle, and reconnect card.
 * Port of React DataSourcePanel.tsx (DataSourceSection).
 */

import {
  ChangeDetectionStrategy,
  Component,
  inject,
  OnInit,
  signal,
} from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@shipagent/shared-api';
import { DataSourceStore, ConversationStore } from '@shipagent/shared-state';
import {
  HardDriveIconComponent,
  InfoIconComponent,
} from '@shipagent/shared-ui';
import { DataSourceMappersService } from './data-source-mappers.service';
import { LocalSourceComponent } from './local-source.component';
import { PlatformSourceComponent } from './platform-source.component';
import { RecentSourcesModalComponent } from '../recent-sources-modal/recent-sources-modal.component';
import type { DataSourceInfo } from '@shipagent/shared-types';

@Component({
  selector: 'sa-data-source-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    HardDriveIconComponent,
    InfoIconComponent,
    LocalSourceComponent,
    PlatformSourceComponent,
    RecentSourcesModalComponent,
  ],
  template: `
    <div class="p-3 space-y-3">
      <span class="text-xs font-medium text-slate-300">Data Sources</span>

      <!-- Platform connections (Shopify, Amazon) -->
      <sa-platform-source />

      <!-- === ACTIVE LOCAL SOURCE CARD === -->
      @if (dataSourceStore.dataSource()?.status === 'connected') {
        <div
          [class]="localSourceCardClass()"
        >
          <div class="flex items-center justify-between p-2.5">
            <div class="flex items-center gap-2">
              <sa-icon-hard-drive class="w-4 h-4 text-slate-400" />
              <span class="text-xs font-medium text-slate-200">{{ localFileName() }}</span>
            </div>
            <div>
              @if (isLocalActive() && conversationStore.interactiveShipping()) {
                <span class="badge badge-neutral text-[9px]">STANDBY</span>
              } @else if (isLocalActive()) {
                <span class="badge badge-success text-[9px]">ACTIVE</span>
              } @else {
                <span class="text-[10px] font-mono text-slate-500">Available</span>
              }
            </div>
          </div>
          <div class="px-2.5 pb-2.5 flex items-center justify-between">
            <div class="flex gap-4 text-[10px] font-mono">
              <span class="text-slate-500">
                Rows: <span [class.text-green-400]="isLocalActive() && !conversationStore.interactiveShipping()" [class.text-slate-400]="!isLocalActive() || conversationStore.interactiveShipping()">{{ dataSourceStore.dataSource()?.row_count?.toLocaleString() || '...' }}</span>
              </span>
              <span class="text-slate-500">
                Cols: <span class="text-slate-300">{{ dataSourceStore.dataSource()?.column_count }}</span>
              </span>
            </div>
            <button
              class="text-[10px] font-mono text-red-400 hover:underline"
              (click)="handleDisconnect()"
            >
              Disconnect
            </button>
          </div>
          @if (isLocalActive() && conversationStore.interactiveShipping()) {
            <div class="px-2.5 pb-2 -mt-1">
              <p class="text-[10px] font-mono text-slate-500">Available in batch mode</p>
            </div>
          }
        </div>
      }

      <!-- === CACHED RECONNECT CARD === -->
      @if (!dataSourceStore.dataSource() && dataSourceStore.cachedLocalConfig()?.file_path) {
        <div class="rounded-lg border border-dashed border-slate-700 p-2.5">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <sa-icon-hard-drive class="w-4 h-4 text-slate-500" />
              <span class="text-xs text-slate-400 truncate">
                {{ lastFileName() }}
              </span>
            </div>
            <button
              class="text-[10px] font-medium text-primary hover:underline disabled:opacity-50"
              [disabled]="isReconnecting()"
              (click)="handleReconnectLocal()"
            >
              @if (isReconnecting()) { Reconnecting... } @else { Reconnect }
            </button>
          </div>
        </div>
      }

      <!-- === WRITE-BACK TOGGLE === -->
      @if (dataSourceStore.activeSourceType() && !conversationStore.interactiveShipping()) {
        <div class="flex items-center justify-between px-3 py-2 mt-1 rounded-md bg-slate-800/50 border border-slate-800/50">
          <div class="flex items-center gap-1.5">
            <label for="write-back-toggle" class="text-[11px] text-slate-400 select-none">
              Sync tracking info
            </label>
            <div class="relative group">
              <sa-icon-info class="w-3.5 h-3.5 text-slate-500 cursor-help" />
              <div class="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-2 py-1.5 bg-slate-800 text-slate-100 text-[10px] rounded shadow-lg opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-150 w-40 text-center leading-relaxed z-50 pointer-events-none">
                Automatically updates tracking numbers on the original data source.
              </div>
            </div>
          </div>
          <!-- Minimal toggle switch -->
          <button
            id="write-back-toggle"
            role="switch"
            class="relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200"
            [class.bg-primary]="dataSourceStore.writeBackEnabled()"
            [class.bg-slate-700]="!dataSourceStore.writeBackEnabled()"
            [attr.aria-checked]="dataSourceStore.writeBackEnabled()"
            (click)="toggleWriteBack()"
          >
            <span
              class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow-sm ring-0 transition duration-200"
              [class.translate-x-4]="dataSourceStore.writeBackEnabled()"
              [class.translate-x-0]="!dataSourceStore.writeBackEnabled()"
            ></span>
          </button>
        </div>
      }

      <!-- === IMPORT SECTION (when no source connected) === -->
      @if (!dataSourceStore.dataSource()?.status) {
        <sa-local-source (openSavedSources)="showRecentSources.set(true)" />
      }

      <!-- Reconnect error -->
      @if (reconnectError()) {
        <p class="text-[10px] font-mono text-red-400 p-2 rounded bg-red-500/10">{{ reconnectError() }}</p>
      }
    </div>

    <!-- Recent Sources Modal -->
    <sa-recent-sources-modal
      [open]="showRecentSources()"
      (closed)="showRecentSources.set(false)"
      (reconnected)="onReconnected($event)"
    />
  `,
})
export class DataSourcePanelComponent implements OnInit {
  readonly dataSourceStore = inject(DataSourceStore);
  readonly conversationStore = inject(ConversationStore);
  private readonly apiService = inject(ApiService);
  private readonly mappers = inject(DataSourceMappersService);

  readonly showRecentSources = signal(false);
  readonly isReconnecting = signal(false);
  readonly reconnectError = signal<string | null>(null);

  ngOnInit(): void {
    this.hydrateSourceStatus();
  }

  /** Whether local source is currently active. */
  isLocalActive(): boolean {
    return this.dataSourceStore.activeSourceType() === 'local';
  }

  /** CSS class string for the local source card — varies by interactive mode. */
  localSourceCardClass(): string {
    const base = 'rounded-lg border overflow-hidden transition-colors';
    if (this.isLocalActive() && this.conversationStore.interactiveShipping()) {
      return `${base} border-l-4 border-l-slate-500 border-slate-600/30 bg-slate-800/20`;
    }
    if (this.isLocalActive()) {
      return `${base} border-l-4 border-l-primary border-primary/30 bg-primary/5`;
    }
    return `${base} border-slate-800`;
  }

  /** Display filename for the connected local source. */
  localFileName(): string {
    const ds = this.dataSourceStore.dataSource();
    if (!ds) return '';
    return this.mappers.extractFileName(ds.csv_path, ds.excel_path, ds.file_path)
      ?? ds.type.toUpperCase();
  }

  /** Filename from cached config for reconnect card. */
  lastFileName(): string {
    const path = this.dataSourceStore.cachedLocalConfig()?.file_path ?? '';
    return path.split('/').pop() ?? path;
  }

  /** Toggle write-back tracking info preference. */
  toggleWriteBack(): void {
    this.dataSourceStore.setWriteBackEnabled(!this.dataSourceStore.writeBackEnabled());
  }

  /** Disconnect the current data source. */
  async handleDisconnect(): Promise<void> {
    try {
      await firstValueFrom(this.apiService.disconnectDataSource());
    } catch {
      // Ignore errors — clear local state regardless
    }
    this.dataSourceStore.clearDataSource();
    this.dataSourceStore.setCachedLocalConfig(null);
  }

  /** Reconnect the previously used local source via saved-sources API. */
  async handleReconnectLocal(): Promise<void> {
    const config = this.dataSourceStore.cachedLocalConfig();
    if (!config?.file_path) return;

    this.isReconnecting.set(true);
    this.reconnectError.set(null);

    try {
      const saved = await firstValueFrom(this.apiService.getSavedSources());
      const fileName = config.file_path.split('/').pop()?.toLowerCase();
      const match = saved.sources.find(
        (s) => s.name.toLowerCase() === fileName,
      );

      if (!match) {
        this.reconnectError.set('Source not found. Please import the file again.');
        return;
      }

      const result = await firstValueFrom(this.apiService.reconnectSavedSource(match.id));
      const source: DataSourceInfo = {
        type: match.source_type,
        status: 'connected',
        row_count: result.row_count,
        column_count: result.column_count,
        connected_at: new Date().toISOString(),
        csv_path: match.source_type === 'csv' ? (match.file_path ?? undefined) : undefined,
        excel_path: match.source_type === 'excel' ? (match.file_path ?? undefined) : undefined,
        file_path: match.file_path ?? undefined,
      };
      this.dataSourceStore.setDataSource(source);
      this.dataSourceStore.setActiveSourceType('local');
    } catch (err) {
      this.reconnectError.set(err instanceof Error ? err.message : 'Reconnect failed');
    } finally {
      this.isReconnecting.set(false);
    }
  }

  /** Handle reconnected source from modal. */
  onReconnected(source: DataSourceInfo): void {
    this.dataSourceStore.setDataSource(source);
    this.dataSourceStore.setActiveSourceType('local');
    this.showRecentSources.set(false);
  }

  /** Hydrate source status from backend on component init. */
  private async hydrateSourceStatus(): Promise<void> {
    try {
      const status = await firstValueFrom(this.apiService.getDataSourceStatus());
      if (!status.connected) return;

      const sourceType = String(status.source_type ?? '').toLowerCase();
      const KNOWN_TYPES = new Set(['csv', 'excel', 'json', 'xml', 'fixed_width', 'edi', 'database']);

      if (KNOWN_TYPES.has(sourceType)) {
        const localType = sourceType as DataSourceInfo['type'];
        const source: DataSourceInfo = {
          type: localType,
          status: 'connected',
          row_count: status.row_count,
          column_count: status.columns?.length,
          columns: status.columns ? this.mappers.mapSchemaColumns(status.columns) : undefined,
          connected_at: new Date().toISOString(),
          csv_path: localType === 'csv' ? status.file_path ?? undefined : undefined,
          excel_path: localType === 'excel' ? status.file_path ?? undefined : undefined,
          file_path: (KNOWN_TYPES.has(localType) && localType !== 'csv' && localType !== 'excel' && localType !== 'database')
            ? status.file_path ?? undefined
            : undefined,
        };
        this.dataSourceStore.setDataSource(source);
        this.dataSourceStore.setActiveSourceType('local');
      } else if (sourceType === 'shopify') {
        this.dataSourceStore.setActiveSourceType('shopify');
      } else if (sourceType === 'amazon') {
        this.dataSourceStore.setActiveSourceType('amazon');
      }
    } catch {
      // Best-effort hydration — keep current UI state on failure
    }
  }
}
