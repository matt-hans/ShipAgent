/**
 * SidebarShellComponent — Collapsible sidebar container.
 *
 * Port of React Sidebar.tsx (outer shell only).
 * Provides the collapse/expand animation and hosts the sidebar-remote
 * content via ng-content projection.
 *
 * The sidebar-remote content is projected using <ng-content> — the shell
 * controls the container width; the remote controls its own content.
 */
import {
  ChangeDetectionStrategy,
  Component,
  Input,
  inject,
} from '@angular/core';
import { AppStore } from '@shipagent/shared-state';
import { ChevronLeftIconComponent, ChevronRightIconComponent } from '@shipagent/shared-ui';
// Icon selectors: sa-icon-chevron-left, sa-icon-chevron-right

@Component({
  selector: 'app-sidebar-shell',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ChevronLeftIconComponent, ChevronRightIconComponent],
  template: `
    <aside
      class="app-sidebar flex flex-col h-full transition-all duration-300 ease-out"
      [class.w-16]="collapsed"
      [class.w-80]="!collapsed"
    >
      <!-- Remote sidebar content projected here (expanded only) -->
      @if (!collapsed) {
        <div class="flex-1 overflow-y-auto scrollable">
          <ng-content />
        </div>
      }

      <!-- Collapsed state — minimal toggle button -->
      @if (collapsed) {
        <div class="flex-1 flex flex-col items-center pt-3 gap-2">
          <button
            (click)="onToggle()"
            class="w-10 h-10 flex items-center justify-center rounded-lg
                   bg-slate-800 text-slate-500 hover:text-slate-300 transition-colors"
            title="Expand sidebar"
          >
            <sa-icon-chevron-right class="w-4 h-4" />
          </button>
        </div>
      }

      <!-- Collapse/expand toggle at bottom -->
      <div class="mt-auto p-3">
        <button
          (click)="onToggle()"
          class="w-full flex items-center justify-center gap-2 py-2 rounded-md
                 hover:bg-slate-800 transition-colors"
          [attr.title]="collapsed ? 'Expand sidebar' : 'Collapse sidebar'"
        >
          @if (collapsed) {
            <sa-icon-chevron-right class="w-4 h-4 text-slate-500" />
          } @else {
            <sa-icon-chevron-left class="w-4 h-4 text-slate-500" />
            <span class="text-xs text-slate-500">Collapse</span>
          }
        </button>
      </div>
    </aside>
  `,
})
export class SidebarShellComponent {
  /** Whether the sidebar is in collapsed (narrow) state. */
  @Input() collapsed = false;

  private readonly appStore = inject(AppStore);

  /** Toggle sidebar collapsed state via AppStore. */
  onToggle(): void {
    this.appStore.toggleSidebar();
  }
}
