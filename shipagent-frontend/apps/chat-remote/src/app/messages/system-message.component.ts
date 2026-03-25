/**
 * SystemMessageComponent — Renders assistant/system messages with GFM markdown.
 *
 * Uses ngx-markdown for GitHub Flavored Markdown rendering (tables, strikethrough,
 * task lists) — matching the React ReactMarkdown + remarkGfm output.
 */

import {
  ChangeDetectionStrategy,
  Component,
  Input,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { MarkdownModule } from 'ngx-markdown';
import { CopyButtonComponent, PackageIconComponent, RelativeTimePipe } from '@shipagent/shared-ui';
import type { ConversationMessage } from '@shipagent/shared-types';

@Component({
  selector: 'app-system-message',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    MarkdownModule,
    CopyButtonComponent,
    PackageIconComponent,
    RelativeTimePipe,
  ],
  template: `
    <div class="flex gap-3 animate-fade-in-up">
      <!-- Avatar -->
      <div class="flex-shrink-0 w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500/20 to-cyan-600/20 border border-cyan-500/30 flex items-center justify-center">
        <sa-icon-package class="w-4 h-4 text-cyan-400" />
      </div>

      <!-- Message content -->
      <div class="flex-1 space-y-1 group">
        <div class="message-system prose prose-invert max-w-none prose-sm prose-p:leading-relaxed prose-pre:bg-slate-800/50 prose-pre:border prose-pre:border-slate-700/50">
          <markdown [data]="message.content" />
        </div>

        <div class="flex items-center gap-1">
          <span class="text-[10px] font-mono text-slate-500">
            {{ message.timestamp | relativeTime }}
          </span>
          <sa-copy-button [text]="message.content" />
        </div>
      </div>
    </div>
  `,
})
export class SystemMessageComponent {
  @Input({ required: true }) message!: ConversationMessage;
}
