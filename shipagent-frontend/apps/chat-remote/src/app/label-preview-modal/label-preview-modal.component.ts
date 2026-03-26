/**
 * LabelPreviewModalComponent — Modal for viewing shipping label PDFs.
 *
 * Fetches the merged PDF via fetch(), creates a blob URL, and embeds it
 * in an iframe. Blob URLs bypass X-Frame-Options: DENY since they are
 * local resources, not HTTP responses.
 *
 * Uses NgZone.run() to ensure signal updates from the async fetch
 * trigger Angular's OnPush change detection.
 */

import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  NgZone,
  OnChanges,
  OnDestroy,
  Output,
  SimpleChanges,
  inject,
  signal,
} from '@angular/core';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';

@Component({
  selector: 'app-label-preview-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (isOpen && pdfUrl) {
      <!-- Backdrop -->
      <div
        class="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
        role="button"
        tabindex="0"
        (click)="close.emit()"
        (keydown.enter)="close.emit()"
      ></div>

      <!-- Modal -->
      <div
        class="fixed inset-0 z-50 flex items-center justify-center p-4"
        role="button"
        tabindex="0"
        (click)="close.emit()"
        (keydown.enter)="close.emit()"
      >
        <div
          class="bg-card border border-border rounded-xl shadow-2xl w-full max-w-[750px] flex flex-col"
          style="height: 85vh;"
          role="dialog"
          (click)="$event.stopPropagation()"
          (keydown.enter)="$event.stopPropagation()"
        >
          <!-- Header -->
          <div class="flex items-center justify-between p-4 border-b border-border flex-shrink-0">
            <h2 class="text-sm font-semibold text-foreground">Label Preview</h2>
            <button
              (click)="close.emit()"
              class="w-8 h-8 flex items-center justify-center rounded-lg text-slate-400 hover:text-foreground hover:bg-muted transition-colors"
              title="Close"
            >
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>

          <!-- PDF content -->
          <div class="flex-1 overflow-hidden min-h-0">
            @if (isLoading()) {
              <div class="flex flex-col items-center justify-center h-full py-16 text-slate-500">
                <div class="w-8 h-8 border-2 border-slate-300 border-t-primary rounded-full animate-spin mb-4"></div>
                <p class="text-sm">Loading labels...</p>
              </div>
            } @else if (errorMsg()) {
              <div class="flex flex-col items-center justify-center h-full py-16 text-red-400">
                <svg class="w-8 h-8 mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
                </svg>
                <p class="text-sm font-medium mb-1">Failed to load labels</p>
                <p class="text-xs text-slate-500">{{ errorMsg() }}</p>
                <button
                  (click)="handleOpenInTab()"
                  class="mt-3 px-4 py-2 text-xs font-medium rounded-lg border border-border text-primary hover:bg-muted transition-colors"
                >
                  Open in new tab instead
                </button>
              </div>
            } @else if (safeBlobUrl) {
              <iframe
                [src]="safeBlobUrl"
                class="w-full h-full border-0"
                title="Shipping labels"
              ></iframe>
            }
          </div>

          <!-- Footer -->
          <div class="flex items-center justify-end gap-2 p-4 border-t border-border flex-shrink-0">
            <button
              (click)="close.emit()"
              class="px-4 py-2 text-sm font-medium rounded-lg border border-border text-slate-300 hover:bg-muted transition-colors"
            >
              Close
            </button>
            <button
              (click)="handlePrint()"
              [disabled]="!safeBlobUrl"
              class="px-4 py-2 text-sm font-medium rounded-lg border border-border text-slate-300 hover:bg-muted transition-colors flex items-center gap-2 disabled:opacity-50"
            >
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <polyline points="6 9 6 2 18 2 18 9" />
                <path d="M6 18H4a2 2 0 01-2-2v-5a2 2 0 012-2h16a2 2 0 012 2v5a2 2 0 01-2 2h-2" />
                <rect x="6" y="14" width="12" height="8" />
              </svg>
              Print
            </button>
            <button
              (click)="handleDownload()"
              [disabled]="!safeBlobUrl"
              class="btn-primary px-4 py-2 text-sm font-medium rounded-lg flex items-center gap-2 disabled:opacity-50"
            >
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
              Download
            </button>
          </div>
        </div>
      </div>
    }
  `,
})
export class LabelPreviewModalComponent implements OnChanges, OnDestroy {
  @Input() pdfUrl = '';
  @Input() isOpen = false;
  @Output() close = new EventEmitter<void>();

  private readonly sanitizer = inject(DomSanitizer);
  private readonly ngZone = inject(NgZone);

  readonly isLoading = signal(true);
  readonly errorMsg = signal<string | null>(null);

  /** Sanitized blob URL safe for iframe [src] binding. */
  safeBlobUrl: SafeResourceUrl | null = null;

  /** Raw blob URL for download/print operations. */
  private rawBlobUrl: string | null = null;

  ngOnChanges(changes: SimpleChanges): void {
    if ((changes['isOpen'] || changes['pdfUrl']) && this.isOpen && this.pdfUrl) {
      this.loadPdf();
    }
  }

  ngOnDestroy(): void {
    this.revokeBlobUrl();
  }

  handlePrint(): void {
    if (!this.rawBlobUrl) return;
    const w = window.open(this.rawBlobUrl, '_blank');
    if (w) w.addEventListener('load', () => w.print());
  }

  handleDownload(): void {
    const url = this.rawBlobUrl || this.pdfUrl;
    const a = document.createElement('a');
    a.href = url;
    a.download = 'labels.pdf';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  handleOpenInTab(): void {
    window.open(this.pdfUrl, '_blank');
  }

  private async loadPdf(): Promise<void> {
    this.revokeBlobUrl();
    // Use NgZone.run for ALL signal updates to ensure OnPush detects changes
    this.ngZone.run(() => {
      this.isLoading.set(true);
      this.errorMsg.set(null);
      this.safeBlobUrl = null;
    });

    try {
      const resp = await fetch(this.pdfUrl);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);

      const contentType = resp.headers.get('content-type') || '';
      if (!contentType.includes('pdf')) {
        throw new Error(`Expected PDF but got ${contentType}`);
      }

      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      this.rawBlobUrl = url;

      this.ngZone.run(() => {
        this.safeBlobUrl = this.sanitizer.bypassSecurityTrustResourceUrl(url);
        this.isLoading.set(false);
      });
    } catch (err) {
      this.ngZone.run(() => {
        this.errorMsg.set(err instanceof Error ? err.message : 'Unknown error');
        this.isLoading.set(false);
      });
    }
  }

  private revokeBlobUrl(): void {
    if (this.rawBlobUrl) {
      URL.revokeObjectURL(this.rawBlobUrl);
      this.rawBlobUrl = null;
      this.safeBlobUrl = null;
    }
  }
}
