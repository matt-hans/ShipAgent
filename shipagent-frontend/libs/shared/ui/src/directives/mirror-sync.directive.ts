/**
 * MirrorSyncDirective — Syncs scroll and dimensions between two elements.
 *
 * Used by the rich text input (RichChatInput) to synchronize a transparent
 * textarea with a visible mirror div that renders syntax-highlighted tokens.
 * Both elements must be identically sized and positioned; the textarea receives
 * input events and the mirror renders the highlighted content on top.
 *
 * Selector: [appMirrorSync]
 *
 * @example
 * <textarea appMirrorSync [mirrorTarget]="mirrorDiv">
 * <div #mirrorDiv class="rich-input-mirror">...</div>
 */

import {
  Directive,
  ElementRef,
  Input,
  OnDestroy,
  OnInit,
} from '@angular/core';

@Directive({
  selector: '[appMirrorSync]',
  standalone: true,
})
export class MirrorSyncDirective implements OnInit, OnDestroy {
  /**
   * The mirror element to sync scroll and dimensions with.
   * Must be passed as a template reference variable.
   */
  @Input() mirrorTarget: HTMLElement | null = null;

  private resizeObserver: ResizeObserver | null = null;
  private readonly scrollHandler: () => void;

  constructor(private readonly el: ElementRef<HTMLElement>) {
    this.scrollHandler = () => this.syncScroll();
  }

  ngOnInit(): void {
    const host = this.el.nativeElement;
    host.addEventListener('scroll', this.scrollHandler);

    if (typeof ResizeObserver !== 'undefined') {
      this.resizeObserver = new ResizeObserver(() => this.syncDimensions());
      this.resizeObserver.observe(host);
    }
  }

  ngOnDestroy(): void {
    const host = this.el.nativeElement;
    host.removeEventListener('scroll', this.scrollHandler);
    this.resizeObserver?.disconnect();
    this.resizeObserver = null;
  }

  /** Synchronize scroll position from host to mirror target. */
  private syncScroll(): void {
    if (!this.mirrorTarget) return;
    const host = this.el.nativeElement;
    this.mirrorTarget.scrollTop = host.scrollTop;
    this.mirrorTarget.scrollLeft = host.scrollLeft;
  }

  /** Synchronize dimensions from host to mirror target via CSS. */
  private syncDimensions(): void {
    if (!this.mirrorTarget) return;
    const host = this.el.nativeElement;
    const rect = host.getBoundingClientRect();
    // Only adjust width/height if they differ to avoid thrashing.
    if (this.mirrorTarget.style.width !== `${rect.width}px`) {
      this.mirrorTarget.style.width = `${rect.width}px`;
    }
    if (this.mirrorTarget.style.height !== `${rect.height}px`) {
      this.mirrorTarget.style.height = `${rect.height}px`;
    }
  }
}
