/**
 * LabelPreviewModalComponent — Full-screen modal for viewing shipping label PDFs.
 *
 * Fetches the merged PDF via fetch(), creates a blob URL, and renders it
 * using an <object> tag. This avoids X-Frame-Options: DENY and CSP issues
 * that block <iframe> same-origin embedding.
 */

import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  OnChanges,
  OnDestroy,
  Output,
  SimpleChanges,
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
        class="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm animate-fade-in"
        (click)="close.emit()"
      ></div>

      <!-- Modal -->
      <div
        class="fixed inset-0 z-50 flex items-center justify-center p-4"
        (click)="close.emit()"
      >
        <div
          class="bg-card border border-border rounded-xl shadow-2xl w-full max-w-[750px] max-h-[90vh] flex flex-col"
          (click)="$event.stopPropagation()"
        >
          <!-- Header -->
          <div class="flex items-center justify-between p-4 border-b border-border">
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
          <div class="flex-1 overflow-hidden bg-white" style="min-height: 500px;">
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
              </div>
            } @else if (blobUrl()) {
              <object
                [data]="safeBlobUrl()"
                type="application/pdf"
                class="w-full h-full"
                style="min-height: 500px;"
              >
                <p class="p-8 text-center text-slate-500">
                  Your browser cannot display PDFs.
                  <a [href]="pdfUrl" target="_blank" class="text-primary underline">Open in new tab</a>
                </p>
              </object>
            }
          </div>

          <!-- Footer -->
          <div class="flex items-center justify-end gap-2 p-4 border-t border-border">
            <button
              (click)="close.emit()"
              class="px-4 py-2 text-sm font-medium rounded-lg border border-border text-slate-300 hover:bg-muted transition-colors"
            >
              Close
            </button>
            <button
              (click)="handlePrint()"
              [disabled]="!blobUrl()"
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
              [disabled]="!blobUrl()"
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

  readonly isLoading = signal(true);
  readonly errorMsg = signal<string | null>(null);
  readonly blobUrl = signal<string | null>(null);

  private sanitizer: DomSanitizer;

  constructor(sanitizer: DomSanitizer) {
    this.sanitizer = sanitizer;
  }

  ngOnChanges(changes: SimpleChanges): void {
    if ((changes['isOpen'] || changes['pdfUrl']) && this.isOpen && this.pdfUrl) {
      this.loadPdf();
    }
  }

  ngOnDestroy(): void {
    this.revokeBlobUrl();
  }

  safeBlobUrl(): SafeResourceUrl {
    return this.sanitizer.bypassSecurityTrustResourceUrl(this.blobUrl()!);
  }

  handlePrint(): void {
    const url = this.blobUrl();
    if (!url) return;
    const w = window.open(url, '_blank');
    if (w) w.addEventListener('load', () => w.print());
  }

  handleDownload(): void {
    const url = this.blobUrl() || this.pdfUrl;
    const a = document.createElement('a');
    a.href = url;
    a.download = 'labels.pdf';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  private async loadPdf(): Promise<void> {
    this.revokeBlobUrl();
    this.isLoading.set(true);
    this.errorMsg.set(null);

    try {
      const resp = await fetch(this.pdfUrl);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      this.blobUrl.set(url);
    } catch (err) {
      this.errorMsg.set(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      this.isLoading.set(false);
    }
  }

  private revokeBlobUrl(): void {
    const url = this.blobUrl();
    if (url) {
      URL.revokeObjectURL(url);
      this.blobUrl.set(null);
    }
  }
}
