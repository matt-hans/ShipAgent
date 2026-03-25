/**
 * SidebarContentComponent
 *
 * Root container for the sidebar remote. Provides three tabbed panels:
 * Data Sources, Job History, and Chat Sessions.
 * Rendered by the shell via NgComponentOutlet.
 */

import {
  ChangeDetectionStrategy,
  Component,
  inject,
  signal,
} from '@angular/core';
import { ConversationStore } from '@shipagent/shared-state';
import { DataSourcePanelComponent } from '../data-source-panel/data-source-panel.component';
import { JobHistoryPanelComponent } from '../job-history-panel/job-history-panel.component';
import { ChatSessionsPanelComponent } from '../chat-sessions-panel/chat-sessions-panel.component';

type ActiveTab = 'data' | 'jobs' | 'chats';

@Component({
  selector: 'sa-sidebar-content',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    DataSourcePanelComponent,
    JobHistoryPanelComponent,
    ChatSessionsPanelComponent,
  ],
  template: `
    <div class="flex flex-col h-full">
      <!-- Tab bar -->
      <div class="flex border-b border-slate-800 flex-shrink-0">
        <button
          class="flex-1 py-2.5 text-[11px] font-medium transition-colors"
          [class.text-slate-100]="activeTab() === 'data'"
          [class.border-b-2]="activeTab() === 'data'"
          [class.border-primary]="activeTab() === 'data'"
          [class.text-slate-500]="activeTab() !== 'data'"
          [class.hover:text-slate-300]="activeTab() !== 'data'"
          (click)="setTab('data')"
        >
          Data
        </button>
        <button
          class="flex-1 py-2.5 text-[11px] font-medium transition-colors"
          [class.text-slate-100]="activeTab() === 'jobs'"
          [class.border-b-2]="activeTab() === 'jobs'"
          [class.border-primary]="activeTab() === 'jobs'"
          [class.text-slate-500]="activeTab() !== 'jobs'"
          [class.hover:text-slate-300]="activeTab() !== 'jobs'"
          (click)="setTab('jobs')"
        >
          Jobs
        </button>
        <button
          class="flex-1 py-2.5 text-[11px] font-medium transition-colors"
          [class.text-slate-100]="activeTab() === 'chats'"
          [class.border-b-2]="activeTab() === 'chats'"
          [class.border-primary]="activeTab() === 'chats'"
          [class.text-slate-500]="activeTab() !== 'chats'"
          [class.hover:text-slate-300]="activeTab() !== 'chats'"
          (click)="setTab('chats')"
        >
          Chats
        </button>
      </div>

      <!-- Panel content — only the active tab is rendered -->
      <div class="flex-1 overflow-y-auto">
        @if (activeTab() === 'data') {
          <sa-data-source-panel />
        }
        @if (activeTab() === 'jobs') {
          <sa-job-history-panel />
        }
        @if (activeTab() === 'chats') {
          <sa-chat-sessions-panel />
        }
      </div>
    </div>
  `,
})
export class SidebarContentComponent {
  readonly conversationStore = inject(ConversationStore);

  /** Active tab signal. */
  readonly activeTab = signal<ActiveTab>('data');

  setTab(tab: ActiveTab): void {
    this.activeTab.set(tab);
  }
}
