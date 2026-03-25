/**
 * ActiveSourceBannerComponent — Shows the currently connected data source.
 */

import {
  ChangeDetectionStrategy,
  Component,
  inject,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { DataSourceStore } from '@shipagent/shared-state';
import { HardDriveIconComponent, ShopifyIconComponent } from '@shipagent/shared-ui';

@Component({
  selector: 'app-active-source-banner',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, HardDriveIconComponent, ShopifyIconComponent],
  template: `
    <div class="flex items-center gap-2 px-4 py-1.5 border-b border-border/50 bg-card/30">
      @if (dataSourceStore.activeSourceInfo()) {
        <span class="w-1.5 h-1.5 rounded-full bg-success flex-shrink-0"></span>
        @if (dataSourceStore.activeSourceType() === 'shopify') {
          <sa-brand-shopify class="w-3.5 h-3.5 text-[#5BBF3D]" />
        } @else {
          <sa-icon-hard-drive class="w-3.5 h-3.5 text-slate-400" />
        }
        <span class="text-xs font-medium text-slate-300">
          {{ dataSourceStore.activeSourceInfo() }}
        </span>
      }
    </div>
  `,
})
export class ActiveSourceBannerComponent {
  readonly dataSourceStore = inject(DataSourceStore);
}
