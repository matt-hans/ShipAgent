import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';

/**
 * Placeholder remote entry component for sidebar-remote.
 * This will be replaced with SidebarContentComponent in Phase 9 Plan 03.
 */
@Component({
  selector: 'app-sidebar-remote-entry',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="card-premium p-4">
      <p class="text-muted-foreground">Sidebar Remote — placeholder (Plan 03 will implement SidebarContentComponent)</p>
    </div>
  `,
})
export class RemoteEntryComponent {}
