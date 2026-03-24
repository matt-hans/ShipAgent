import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';

/**
 * Placeholder remote entry component for chat-remote.
 * This will be replaced with ChatContainerComponent in Phase 9 Plan 02.
 */
@Component({
  selector: 'app-chat-remote-entry',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="card-premium p-4">
      <p class="text-muted-foreground">Chat Remote — placeholder (Plan 02 will implement ChatContainerComponent)</p>
    </div>
  `,
})
export class RemoteEntryComponent {}
