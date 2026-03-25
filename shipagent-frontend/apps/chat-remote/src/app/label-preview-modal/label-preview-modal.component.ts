/**
 * LabelPreviewModalComponent — Full-screen modal for viewing shipping label PDFs.
 *
 * Displays a merged PDF in an iframe with print and download actions.
 * Matches the React LabelPreview dialog pattern:
 *   - Full-screen backdrop overlay (fixed inset-0 z-50)
 *   - Centered modal card with header, iframe body, and footer buttons
 *   - Close on backdrop click or X button
 *   - Print opens the PDF in a new window and triggers browser print
 *   - Download creates a temporary anchor element for file save
 */

import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
  inject,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';

@Component({
  selector: 'app-label-preview-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule],
  template: `
    @if (isOpen && pdfUrl) {
      <!-- Backdrop -->
      <div
        class="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
        (click)="close.emit()"
      ></div>

      <!-- Modal -->
      <div
        class="fixed inset-0 z-50 flex items-center justify-center p-4"
        (click)="close.emit()"
      >
        <div
          class="bg-card border border-border rounded-xl shadow-2xl w-full max-w-[700px] max-h-[90vh] flex flex-col"
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

          <!-- PDF iframe -->
          <div class="flex-1 overflow-hidden min-h-[400px] bg-muted/30">
            <iframe
              [src]="safePdfUrl"
              class="w-full h-full border-0"
              style="min-height: 400px"
              title="Shipping labels"
            ></iframe>
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
              class="px-4 py-2 text-sm font-medium rounded-lg border border-border text-slate-300 hover:bg-muted transition-colors flex items-center gap-2"
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
              class="btn-primary px-4 py-2 text-sm font-medium rounded-lg flex items-center gap-2"
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
export class LabelPreviewModalComponent {
  /** URL pointing to the merged labels PDF endpoint. */
  @Input() pdfUrl = '';

  /** Whether the modal is visible. */
  @Input() isOpen = false;

  /** Emitted when the user closes the modal (backdrop, X, or Close button). */
  @Output() close = new EventEmitter<void>();

  private readonly sanitizer = inject(DomSanitizer);

  /** Sanitized URL safe for iframe [src] binding. */
  get safePdfUrl(): SafeResourceUrl {
    return this.sanitizer.bypassSecurityTrustResourceUrl(this.pdfUrl);
  }

  /** Open the PDF in a new window and trigger the browser print dialog. */
  handlePrint(): void {
    const w = window.open(this.pdfUrl, '_blank');
    if (w) {
      w.addEventListener('load', () => w.print());
    }
  }

  /** Trigger a file download via a temporary anchor element. */
  handleDownload(): void {
    const a = document.createElement('a');
    a.href = this.pdfUrl;
    a.download = 'labels.pdf';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }
}
