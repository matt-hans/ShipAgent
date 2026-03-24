/**
 * CopyButtonComponent — Hover-reveal clipboard copy button.
 *
 * Shows a copy icon on hover with visual feedback states (copied/error).
 * Uses navigator.clipboard.writeText() and resets after 2 seconds.
 *
 * Port of the inline CopyButton from the React messages component.
 */

import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  Input,
  OnDestroy,
} from '@angular/core';
import { NgClass } from '@angular/common';

type CopyState = 'idle' | 'copied' | 'error';

@Component({
  selector: 'sa-copy-button',
  standalone: true,
  imports: [NgClass],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <button
      type="button"
      [title]="copyState === 'copied' ? 'Copied!' : copyState === 'error' ? 'Failed' : 'Copy'"
      [ngClass]="buttonClasses"
      (click)="copy()"
    >
      @if (copyState === 'copied') {
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="w-3.5 h-3.5">
          <polyline points="20 6 9 17 4 12" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      } @else if (copyState === 'error') {
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="w-3.5 h-3.5">
          <line x1="18" y1="6" x2="6" y2="18" stroke-linecap="round" stroke-linejoin="round" />
          <line x1="6" y1="6" x2="18" y2="18" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      } @else {
        <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
          <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
        </svg>
      }
    </button>
  `,
  styles: [`
    :host {
      display: inline-flex;
    }
  `],
})
export class CopyButtonComponent implements OnDestroy {
  /** The text content to copy to the clipboard. */
  @Input() text = '';

  protected copyState: CopyState = 'idle';
  private resetTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(private readonly cdr: ChangeDetectorRef) {}

  get buttonClasses(): Record<string, boolean> {
    return {
      'p-1 rounded transition-colors duration-150 opacity-0 group-hover:opacity-100 focus:opacity-100': true,
      'text-muted-foreground hover:text-foreground': this.copyState === 'idle',
      'text-success': this.copyState === 'copied',
      'text-destructive': this.copyState === 'error',
    };
  }

  protected async copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(this.text);
      this.copyState = 'copied';
    } catch {
      this.copyState = 'error';
    }

    this.cdr.markForCheck();
    this.scheduleReset();
  }

  private scheduleReset(): void {
    if (this.resetTimer) clearTimeout(this.resetTimer);
    this.resetTimer = setTimeout(() => {
      this.copyState = 'idle';
      this.cdr.markForCheck();
    }, 2000);
  }

  ngOnDestroy(): void {
    if (this.resetTimer) clearTimeout(this.resetTimer);
  }
}
