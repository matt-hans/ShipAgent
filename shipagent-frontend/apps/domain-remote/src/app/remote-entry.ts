import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';

/**
 * Placeholder remote entry component for domain-remote.
 * This will be replaced with DomainCardRegistryComponent in Phase 9 Plan 05.
 */
@Component({
  selector: 'app-domain-remote-entry',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="card-premium p-4">
      <p class="text-muted-foreground">Domain Remote — placeholder (Plan 05 will implement DomainCardRegistryComponent)</p>
    </div>
  `,
})
export class RemoteEntryComponent {}
