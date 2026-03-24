/**
 * AppComponent — Shell root layout component.
 *
 * This file contains the placeholder component that will be replaced
 * with the full layout (header + sidebar + main + flyout) in Task 2.
 * It exists here to satisfy the bootstrap.ts import during Task 1 compilation.
 */
import { Component, ChangeDetectionStrategy } from '@angular/core';

@Component({
  selector: 'app-root',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<div>Loading ShipAgent...</div>`,
})
export class AppComponent {}
