/**
 * WelcomeMessageComponent — First-time welcome screen with feature highlights.
 *
 * Context-aware: shows different content based on interactive mode and
 * whether a data source is connected.
 */

import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
  inject,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { DataSourceStore } from '@shipagent/shared-state';
import { PackageIconComponent } from '@shipagent/shared-ui';

interface ExampleCommand {
  text: string;
  desc: string;
}

@Component({
  selector: 'app-welcome-message',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, PackageIconComponent],
  template: `
    @if (interactiveShipping) {
      <!-- Interactive mode welcome -->
      <div class="flex flex-col items-center pt-12 text-center px-4 animate-fade-in">
        <div class="flex h-12 w-12 items-center justify-center rounded-lg bg-primary mb-4">
          <sa-icon-package class="h-6 w-6 text-primary-foreground" />
        </div>
        <h2 class="text-xl font-semibold text-foreground mb-2">Single Shipment</h2>
        <p class="text-sm text-slate-400 max-w-md mb-6">
          Create one shipment from scratch in natural language.<br />
          ShipAgent will ask for any missing required details.
        </p>
        <div class="space-y-3 w-full max-w-md">
          <p class="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Click to try</p>
          <div class="space-y-2">
            @for (example of interactiveExamples; track example.text) {
              <button
                (click)="exampleClick.emit(example.text)"
                class="w-full px-4 py-3 rounded-lg bg-slate-800/50 border border-slate-700/50 text-left hover:bg-slate-800 hover:border-slate-600 transition-colors group"
              >
                <p class="text-sm text-slate-300 group-hover:text-slate-100">"{{ example.text }}"</p>
                <p class="text-[10px] text-slate-600 mt-0.5">{{ example.desc }}</p>
              </button>
            }
          </div>
        </div>
      </div>

    } @else if (!isConnected) {
      <!-- No data source connected -->
      <div class="flex flex-col items-center pt-12 text-center px-4 animate-fade-in">
        <div class="flex h-12 w-12 items-center justify-center rounded-lg bg-primary mb-4">
          <sa-icon-package class="h-6 w-6 text-primary-foreground" />
        </div>
        <h2 class="text-xl font-semibold text-foreground mb-2">Welcome to ShipAgent</h2>
        <p class="text-sm text-slate-400 max-w-md mb-6">
          Natural language batch shipment processing powered by AI.<br />
          Connect a data source from the sidebar to get started.
        </p>

        <div class="grid grid-cols-3 gap-4 w-full max-w-lg mb-6">
          @for (item of steps; track item.step) {
            <div class="text-center">
              <div class="w-8 h-8 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center mx-auto mb-2">
                <span class="text-xs font-mono text-primary">{{ item.step }}</span>
              </div>
              <p class="text-xs font-medium text-slate-200">{{ item.title }}</p>
              <p class="text-[10px] text-slate-500">{{ item.desc }}</p>
            </div>
          }
        </div>

        <div class="space-y-2 w-full max-w-md opacity-50">
          <p class="text-[10px] font-mono text-slate-600 uppercase tracking-wider">Example commands</p>
          <div class="space-y-1.5">
            @for (example of batchExamples; track example.text) {
              <div class="px-3 py-2 rounded-lg bg-slate-800/30 border border-slate-800/50 text-left">
                <p class="text-xs text-slate-500">"{{ example.text }}"</p>
              </div>
            }
          </div>
        </div>
      </div>

    } @else {
      <!-- Data source connected, ready to ship -->
      <div class="flex flex-col items-center pt-12 text-center px-4 animate-fade-in">
        <div class="flex h-12 w-12 items-center justify-center rounded-lg bg-primary mb-4">
          <sa-icon-package class="h-6 w-6 text-primary-foreground" />
        </div>
        <h2 class="text-xl font-semibold text-foreground mb-2">Ready to Ship</h2>
        <p class="text-sm text-slate-400 max-w-md mb-2">
          Connected to <span class="text-primary font-medium">{{ dataSourceStore.activeSourceInfo() }}</span>
        </p>
        <p class="text-xs text-slate-500 max-w-md mb-6">
          Describe what you want to ship in natural language. ShipAgent will parse your intent,
          filter your data, and generate a preview for your approval.
        </p>
        <div class="space-y-3 w-full max-w-md">
          <p class="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Click to try</p>
          <div class="space-y-2">
            @for (example of batchExamples; track example.text) {
              <button
                (click)="exampleClick.emit(example.text)"
                class="w-full px-4 py-3 rounded-lg bg-slate-800/50 border border-slate-700/50 text-left hover:bg-slate-800 hover:border-slate-600 transition-colors group"
              >
                <p class="text-sm text-slate-300 group-hover:text-slate-100">"{{ example.text }}"</p>
                <p class="text-[10px] text-slate-600 mt-0.5">{{ example.desc }}</p>
              </button>
            }
          </div>
        </div>
      </div>
    }
  `,
})
export class WelcomeMessageComponent {
  @Input() interactiveShipping = false;
  @Output() exampleClick = new EventEmitter<string>();

  readonly dataSourceStore = inject(DataSourceStore);

  get isConnected(): boolean {
    return !!this.dataSourceStore.activeSourceInfo();
  }

  readonly batchExamples: ExampleCommand[] = [
    { text: 'Ship all California orders using UPS Ground', desc: 'Filter by state' },
    { text: "Ship today's pending orders with 2nd Day Air", desc: 'Filter by status & date' },
    { text: 'Create shipments for orders over $100', desc: 'Filter by amount' },
  ];

  readonly interactiveExamples: ExampleCommand[] = [
    {
      text: 'Ship a 5lb box to John Smith at 123 Main St, Springfield IL 62704 via Ground',
      desc: 'Single shipment',
    },
    {
      text: 'Create a Next Day Air shipment to 456 Oak Ave, Austin TX 78701',
      desc: 'Express shipment',
    },
  ];

  readonly steps = [
    { step: '1', title: 'Connect', desc: 'File, database, or platform' },
    { step: '2', title: 'Describe', desc: 'Natural language command' },
    { step: '3', title: 'Ship', desc: 'Preview, approve, execute' },
  ];
}
