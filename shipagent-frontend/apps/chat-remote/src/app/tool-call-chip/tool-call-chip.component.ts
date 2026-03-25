/**
 * ToolCallChipComponent — Animated chip showing the active tool call.
 *
 * Displayed while the agent is executing a tool. Fades out when the tool
 * call completes.
 */

import {
  ChangeDetectionStrategy,
  Component,
  Input,
} from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-tool-call-chip',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule],
  styles: [`
    .chip-pulse {
      animation: chip-fade-in 0.2s ease-out;
    }
    @keyframes chip-fade-in {
      from { opacity: 0; transform: translateY(4px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .dot-blink {
      animation: dot-blink 1s infinite;
    }
    @keyframes dot-blink {
      0%, 100% { opacity: 0.3; }
      50% { opacity: 1; }
    }
  `],
  template: `
    @if (isActive && toolName) {
      <div class="flex items-center gap-2 px-3 py-1.5 rounded-full bg-primary/10 border border-primary/30 text-primary chip-pulse w-fit">
        <span class="w-1.5 h-1.5 rounded-full bg-primary dot-blink flex-shrink-0"></span>
        <span class="text-xs font-mono">{{ toolName }}</span>
      </div>
    }
  `,
})
export class ToolCallChipComponent {
  /** The tool name to display. */
  @Input() toolName = '';
  /** Whether the tool call is currently active. */
  @Input() isActive = false;
}
