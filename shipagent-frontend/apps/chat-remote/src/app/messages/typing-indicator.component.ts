/**
 * TypingIndicatorComponent — Three-dot animation while agent is responding.
 */

import { ChangeDetectionStrategy, Component } from '@angular/core';
import { PackageIconComponent } from '@shipagent/shared-ui';

@Component({
  selector: 'app-typing-indicator',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [PackageIconComponent],
  styles: [`
    .typing-indicator {
      display: flex;
      align-items: center;
      gap: 4px;
    }
    .typing-indicator span {
      display: inline-block;
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background-color: oklch(0.65 0.15 190);
      animation: typing-bounce 1.4s infinite ease-in-out;
    }
    .typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
    .typing-indicator span:nth-child(3) { animation-delay: 0.4s; }
    @keyframes typing-bounce {
      0%, 80%, 100% { transform: translateY(0); opacity: 0.4; }
      40% { transform: translateY(-6px); opacity: 1; }
    }
  `],
  template: `
    <div class="flex gap-3 animate-fade-in">
      <div class="flex-shrink-0 w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500/20 to-cyan-600/20 border border-cyan-500/30 flex items-center justify-center">
        <sa-icon-package class="w-4 h-4 text-cyan-400" />
      </div>

      <div class="message-system py-3">
        <div class="typing-indicator">
          <span></span>
          <span></span>
          <span></span>
        </div>
      </div>
    </div>
  `,
})
export class TypingIndicatorComponent {}
