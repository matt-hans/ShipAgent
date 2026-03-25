/**
 * PreviewActionsComponent — Shared confirm/cancel/refine actions for preview cards.
 *
 * Sticky footer with three actions:
 *   - Confirm: execute the batch
 *   - Cancel: discard the preview
 *   - Refine: show text input for a follow-up refinement message
 *
 * Used by BatchPreviewComponent and InteractivePreviewComponent.
 */

import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

@Component({
  selector: 'app-preview-actions',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormsModule],
  styles: [`
    .sticky-footer {
      position: sticky;
      bottom: 0;
      background: oklch(0.12 0.01 240 / 0.95);
      backdrop-filter: blur(4px);
      border-top: 1px solid oklch(0.25 0.02 240 / 0.5);
      padding: 0.75rem;
    }
  `],
  template: `
    <div class="sticky-footer">
      @if (!isRefining()) {
        <!-- Normal actions row -->
        <div class="flex items-center gap-2">
          <button
            type="button"
            class="btn-primary flex-1 py-2 text-sm font-medium"
            [disabled]="isConfirming"
            (click)="confirm.emit()"
          >
            @if (isConfirming) {
              <span class="opacity-60">Confirming...</span>
            } @else {
              Confirm &amp; Execute
            }
          </button>

          <button
            type="button"
            class="btn-secondary px-4 py-2 text-sm"
            [disabled]="isConfirming"
            (click)="isRefining.set(true)"
          >
            Refine
          </button>

          <button
            type="button"
            class="btn-secondary px-4 py-2 text-sm text-error/80 hover:text-error"
            [disabled]="isConfirming"
            (click)="cancel.emit()"
          >
            Cancel
          </button>
        </div>
      } @else {
        <!-- Refinement input row -->
        <div class="space-y-2">
          <textarea
            class="w-full bg-card/50 border border-border/50 rounded-lg px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground outline-none focus:border-primary/50 resize-none"
            placeholder="Describe your refinement..."
            rows="2"
            [value]="refineText()"
            (input)="refineText.set($any($event.target).value)"
            (keydown)="handleRefineKeyDown($event)"
          ></textarea>

          <div class="flex items-center gap-2">
            <button
              type="button"
              class="btn-primary flex-1 py-1.5 text-sm"
              [disabled]="!refineText().trim()"
              (click)="submitRefinement()"
            >
              Send Refinement
            </button>
            <button
              type="button"
              class="btn-secondary px-4 py-1.5 text-sm"
              (click)="cancelRefinement()"
            >
              Back
            </button>
          </div>
        </div>
      }
    </div>
  `,
})
export class PreviewActionsComponent {
  @Input() isConfirming = false;

  @Output() confirm = new EventEmitter<void>();
  @Output() cancel = new EventEmitter<void>();
  @Output() refine = new EventEmitter<string>();

  readonly isRefining = signal(false);
  readonly refineText = signal('');

  submitRefinement(): void {
    const text = this.refineText().trim();
    if (!text) return;
    this.refine.emit(text);
    this.isRefining.set(false);
    this.refineText.set('');
  }

  cancelRefinement(): void {
    this.isRefining.set(false);
    this.refineText.set('');
  }

  handleRefineKeyDown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.submitRefinement();
    }
    if (event.key === 'Escape') {
      this.cancelRefinement();
    }
  }
}
