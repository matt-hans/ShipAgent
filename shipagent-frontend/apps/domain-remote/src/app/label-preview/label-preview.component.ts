/**
 * LabelPreviewComponent
 *
 * Port of React LabelPreview.tsx.
 * Renders PDF shipping labels in-browser using ng2-pdf-viewer.
 * Provides download and print actions.
 * Handles loading and error states.
 */

import {
  Component,
  Input,
  ChangeDetectionStrategy,
  signal,
  OnChanges,
  SimpleChanges,
} from '@angular/core';
import { PdfViewerModule } from 'ng2-pdf-viewer';
import {
  LoadingIconComponent,
  AlertIconComponent,
  PrinterIconComponent,
  DownloadIconComponent,
} from '@shipagent/shared-ui';

@Component({
  selector: 'app-label-preview',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    PdfViewerModule,
    LoadingIconComponent,
    AlertIconComponent,
    PrinterIconComponent,
    DownloadIconComponent,
  ],
  template: `
    <div class="flex flex-col h-full">
      <!-- Header -->
      <div class="flex items-center justify-between px-4 py-3 border-b border-border">
        <h4 class="text-sm font-medium text-foreground">
          {{ title || 'Label Preview' }}
        </h4>
        @if (trackingNumber) {
          <code class="text-xs font-mono text-muted-foreground">{{ trackingNumber }}</code>
        }
      </div>

      <!-- PDF viewer -->
      <div class="flex-1 overflow-y-auto min-h-0 bg-muted/30 p-4">
        @if (isLoading()) {
          <div class="flex flex-col items-center justify-center py-16 text-muted-foreground">
            <sa-icon-loading class="h-8 w-8 animate-spin mb-4" />
            <p class="text-sm">Loading label...</p>
          </div>
        }

        @if (loadError()) {
          <div class="flex flex-col items-center justify-center py-16 text-error">
            <sa-icon-alert class="h-8 w-8 mb-4" />
            <p class="text-sm font-medium mb-2">Failed to load label</p>
            <p class="text-xs text-muted-foreground">{{ loadError() }}</p>
          </div>
        }

        @if (!loadError() && resolvedUrl) {
          <pdf-viewer
            [src]="resolvedUrl"
            [render-text]="false"
            [original-size]="false"
            [fit-to-page]="true"
            [zoom]="1"
            [show-all]="true"
            [page]="1"
            (after-load-complete)="onLoadComplete($event)"
            (error)="onLoadError($event)"
            style="display: block; width: 100%;"
          />
        }
      </div>

      <!-- Footer actions -->
      <div class="flex items-center justify-end gap-2 px-4 py-3 border-t border-border">
        <button
          (click)="handlePrint()"
          [disabled]="isLoading() || !!loadError()"
          class="btn-secondary py-1.5 px-3 flex items-center gap-2 text-sm disabled:opacity-50"
        >
          <sa-icon-printer class="w-4 h-4" />
          <span>Print</span>
        </button>
        <button
          (click)="handleDownload()"
          [disabled]="isLoading() || !!loadError()"
          class="btn-primary py-1.5 px-3 flex items-center gap-2 text-sm disabled:opacity-50"
        >
          <sa-icon-download class="w-4 h-4" />
          <span>Download</span>
        </button>
      </div>
    </div>
  `,
})
export class LabelPreviewComponent implements OnChanges {
  /** Tracking number for single-label view (used to build URL and filename). */
  @Input() trackingNumber?: string;

  /** Job ID for per-row label access. */
  @Input() jobId?: string;

  /** Row number for per-row label access. */
  @Input() rowNumber?: number;

  /** Direct PDF URL (takes precedence over derived URLs). */
  @Input() labelUrl?: string;

  /** Display title in the header. */
  @Input() title?: string;

  readonly isLoading = signal(true);
  readonly loadError = signal<string | null>(null);

  /** Resolved URL computed from inputs. */
  get resolvedUrl(): string {
    if (this.labelUrl) return this.labelUrl;
    if (this.jobId && this.rowNumber != null) {
      return `/api/v1/jobs/${this.jobId}/labels/${this.rowNumber}`;
    }
    if (this.trackingNumber) {
      return `/api/v1/labels/${this.trackingNumber}`;
    }
    return '';
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (
      changes['labelUrl'] ||
      changes['trackingNumber'] ||
      changes['jobId'] ||
      changes['rowNumber']
    ) {
      this.isLoading.set(true);
      this.loadError.set(null);
    }
  }

  onLoadComplete(pdf: { numPages: number }): void {
    this.isLoading.set(false);
    this.loadError.set(null);
  }

  onLoadError(error: unknown): void {
    this.isLoading.set(false);
    const message =
      error instanceof Error
        ? error.message
        : 'Could not load PDF';
    this.loadError.set(message);
  }

  handleDownload(): void {
    const url = this.resolvedUrl;
    if (!url) return;
    const link = document.createElement('a');
    link.href = url;
    link.download = this.trackingNumber
      ? `${this.trackingNumber}.pdf`
      : 'labels.pdf';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  handlePrint(): void {
    const url = this.resolvedUrl;
    if (!url) return;
    const printWindow = window.open(url, '_blank');
    if (printWindow) {
      printWindow.addEventListener('load', () => {
        printWindow.print();
      });
    }
  }
}
