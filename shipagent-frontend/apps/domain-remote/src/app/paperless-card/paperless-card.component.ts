/**
 * PaperlessCardComponent
 *
 * Port of React PaperlessCard.tsx.
 * Renders paperless document operation results (uploaded/pushed/deleted).
 * Domain color: paperless/amber via card-domain-paperless CSS class.
 */

import { Component, Input, ChangeDetectionStrategy } from '@angular/core';
import { CheckIconComponent, FileIconComponent } from '@shipagent/shared-ui';
import type { PaperlessResult } from '@shipagent/shared-types';

interface ActionMeta {
  label: string;
  description: string;
}

const ACTION_META: Record<PaperlessResult['action'], ActionMeta> = {
  uploaded: { label: 'Document Uploaded', description: 'Document uploaded to UPS Forms History.' },
  pushed: { label: 'Document Attached', description: 'Document attached to shipment.' },
  deleted: { label: 'Document Deleted', description: 'Document removed from Forms History.' },
};

const DOCUMENT_TYPE_LABELS: Record<string, string> = {
  '002': 'Commercial Invoice',
  '003': 'Certificate of Origin',
  '004': 'NAFTA Certificate',
  '005': 'Partial Invoice',
  '006': 'Packing List',
  '007': 'Customer Generated Forms',
  '008': 'Air Freight Invoice',
  '009': 'Proforma Invoice',
  '010': 'SED',
  '011': 'Weight Certificate',
};

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

@Component({
  selector: 'app-paperless-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CheckIconComponent, FileIconComponent],
  template: `
    <div class="card-premium p-4 space-y-3 border-l-4 card-domain-paperless">
      <!-- Header -->
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-2">
          <sa-icon-file class="w-4 h-4 text-[var(--color-domain-paperless)]" />
          <h4 class="text-sm font-medium text-foreground">{{ meta.label }}</h4>
        </div>
        <span class="badge badge-success">
          <sa-icon-check class="w-3 h-3 mr-1" />
          Done
        </span>
      </div>

      <p class="text-xs text-muted-foreground">{{ meta.description }}</p>

      <!-- File metadata block -->
      @if (hasFileInfo) {
        <div class="flex items-center gap-2 px-3 py-2 rounded-md bg-muted">
          <sa-icon-file class="w-4 h-4 text-[var(--color-domain-paperless)] shrink-0" />
          <div class="flex-1 min-w-0">
            @if (data.fileName) {
              <p class="text-xs font-medium text-foreground truncate">{{ data.fileName }}</p>
            }
            <p class="text-[10px] text-muted-foreground">{{ fileMetaSummary }}</p>
          </div>
        </div>
      }

      @if (documentIds.length > 0) {
        <div class="flex items-center gap-2 text-xs font-mono px-2 py-1.5 rounded bg-muted">
          <span class="text-muted-foreground">{{ documentIds.length > 1 ? 'Document IDs:' : 'Document ID:' }}</span>
          <span class="text-foreground break-all">{{ documentIds.join(', ') }}</span>
        </div>
      }

      @if (data.formsGroupId) {
        <div class="flex items-center gap-2 text-xs font-mono px-2 py-1.5 rounded bg-muted">
          <span class="text-muted-foreground">Forms Group ID:</span>
          <span class="text-foreground break-all">{{ data.formsGroupId }}</span>
        </div>
      }

      @if (statusText) {
        <div class="text-xs px-2 py-1.5 rounded bg-muted/70">
          <span class="text-muted-foreground">UPS Response:</span>&nbsp;
          <span class="text-foreground">{{ statusText }}</span>
        </div>
      }

      @if (data.customerContext) {
        <div class="text-xs px-2 py-1.5 rounded bg-muted/70">
          <span class="text-muted-foreground">Customer Context:</span>&nbsp;
          <span class="text-foreground break-all">{{ data.customerContext }}</span>
        </div>
      }

      @if (hasAlerts) {
        <div class="text-xs px-2 py-1.5 rounded bg-muted/70 space-y-1">
          <p class="text-muted-foreground">UPS Alerts:</p>
          @for (alert of data.alerts; track $index) {
            <p class="text-foreground">{{ formatAlert(alert) }}</p>
          }
        </div>
      }
    </div>
  `,
})
export class PaperlessCardComponent {
  @Input({ required: true }) data!: PaperlessResult;

  get meta(): ActionMeta {
    return ACTION_META[this.data?.action] ?? ACTION_META.uploaded;
  }

  get hasFileInfo(): boolean {
    return Boolean(this.data?.fileName || this.data?.fileFormat || this.data?.documentType);
  }

  get docTypeLabel(): string | null {
    return this.data?.documentType
      ? DOCUMENT_TYPE_LABELS[this.data.documentType] || this.data.documentType
      : null;
  }

  get fileMetaSummary(): string {
    return [
      this.docTypeLabel,
      this.data?.fileFormat?.toUpperCase(),
      this.data?.fileSizeBytes != null ? formatFileSize(this.data.fileSizeBytes) : null,
    ]
      .filter(Boolean)
      .join(' · ');
  }

  get documentIds(): string[] {
    if (Array.isArray(this.data?.documentIds) && this.data.documentIds.length > 0) {
      return this.data.documentIds;
    }
    return this.data?.documentId ? [this.data.documentId] : [];
  }

  get statusText(): string {
    return [this.data?.statusCode, this.data?.statusDescription].filter(Boolean).join(' · ');
  }

  get hasAlerts(): boolean {
    return Array.isArray(this.data?.alerts) && (this.data.alerts?.length ?? 0) > 0;
  }

  protected formatAlert(alert: { code?: string; message?: string }): string {
    return [alert.code, alert.message].filter((v) => v != null && v !== '').join(': ');
  }
}
