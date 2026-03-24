/**
 * Generic test host component for testing Angular components with content projection.
 *
 * Use this when you need to test a component's ng-content slots or
 * wrap a component in a parent for integration testing.
 *
 * @example
 * ```typescript
 * @Component({
 *   template: `<app-my-card><p>Projected content</p></app-my-card>`,
 *   imports: [MyCardComponent],
 * })
 * class TestHostComponent extends TestHostBase {}
 * ```
 */

import { Component } from '@angular/core';

/**
 * Base class for test host components.
 * Extend this class to create purpose-specific test hosts with type safety.
 */
@Component({
  selector: 'sa-test-host',
  template: `<ng-content></ng-content>`,
  standalone: true,
})
export class TestHostComponent {}

/**
 * Create an inline test host component with the given template and imports.
 * Useful for one-off test scenarios without defining a new class.
 *
 * @param template - Angular template string.
 * @param imports - Component imports for the host.
 * @returns A Component class configured for testing.
 */
export function createTestHost(
  template: string,
  imports: unknown[] = [],
): typeof TestHostComponent {
  @Component({
    selector: 'sa-test-host-dynamic',
    template,
    standalone: true,
    imports: imports as Parameters<typeof Component>[0]['imports'],
  })
  class DynamicTestHostComponent extends TestHostComponent {}

  return DynamicTestHostComponent;
}
