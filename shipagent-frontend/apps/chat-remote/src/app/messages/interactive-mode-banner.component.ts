/**
 * InteractiveModeBannerComponent — Shows when interactive shipping mode is active.
 */

import { ChangeDetectionStrategy, Component } from '@angular/core';

@Component({
  selector: 'app-interactive-mode-banner',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="flex items-center gap-2 px-4 py-1.5 border-b border-amber-500/20 bg-amber-500/5">
      <span class="w-1.5 h-1.5 rounded-full bg-amber-400 flex-shrink-0"></span>
      <span class="text-xs font-medium text-amber-200">Single Shipment</span>
    </div>
  `,
})
export class InteractiveModeBannerComponent {}
