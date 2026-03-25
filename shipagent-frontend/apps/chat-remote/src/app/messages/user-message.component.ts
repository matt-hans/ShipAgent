/**
 * UserMessageComponent — Renders user messages in the chat thread.
 */

import {
  ChangeDetectionStrategy,
  Component,
  Input,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { CopyButtonComponent, RelativeTimePipe } from '@shipagent/shared-ui';
import type { ConversationMessage } from '@shipagent/shared-types';

@Component({
  selector: 'app-user-message',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, CopyButtonComponent, RelativeTimePipe],
  template: `
    <div class="flex gap-3 justify-end animate-fade-in-up">
      <div class="flex-1 space-y-1 flex flex-col items-end group">
        <div class="message-user">
          <p class="text-sm whitespace-pre-wrap">{{ message.content }}</p>
        </div>

        <div class="flex items-center gap-1">
          <sa-copy-button [text]="message.content" />
          <span class="text-[10px] font-mono text-slate-500">
            {{ message.timestamp | relativeTime }}
          </span>
        </div>
      </div>
    </div>
  `,
})
export class UserMessageComponent {
  @Input({ required: true }) message!: ConversationMessage;
}
