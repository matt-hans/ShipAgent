/**
 * Spartan UI Setup
 *
 * This module provides the Spartan UI integration for ShipAgent.
 * All Spartan brain (behavior) primitives are available via @spartan-ng/brain imports.
 *
 * Usage in components:
 *   import { BrnDialogModule } from '@spartan-ng/brain/dialog';
 *   import { BrnSwitchModule } from '@spartan-ng/brain/switch';
 *   import { BrnPopoverModule } from '@spartan-ng/brain/popover';
 *   import { BrnTooltipModule } from '@spartan-ng/brain/tooltip';
 *   import { BrnScrollAreaModule } from '@spartan-ng/brain/scroll-area';
 *   import { BrnProgressModule } from '@spartan-ng/brain/progress';
 *
 * Note: Spartan helm (HTML) wrapper components are created on-demand in each remote.
 * The @spartan-ng/brain package provides the accessible headless primitives.
 * Run `nx g @spartan-ng/cli:ui --name=<component>` to scaffold helm wrappers when needed.
 *
 * Currently installed: @spartan-ng/brain@latest, @angular/cdk@latest
 */

// Re-export nothing — Spartan brain modules are imported directly by consuming components.
// This file documents the Spartan setup for the project.
export {};
