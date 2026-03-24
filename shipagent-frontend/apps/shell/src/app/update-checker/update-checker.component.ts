/**
 * UpdateCheckerComponent — Tauri auto-updater integration.
 *
 * Port of React UpdateChecker.tsx.
 * Only activates when running inside the Tauri desktop wrapper.
 * Checks for updates via @tauri-apps/plugin-updater and shows a banner
 * when an update is available.
 */
import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  inject,
  signal,
} from '@angular/core';
import { TauriDetectionService } from '@shipagent/shared-tauri';

@Component({
  selector: 'app-update-checker',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (updateAvailable()) {
      <div
        class="fixed bottom-4 right-4 z-40 flex items-center gap-3 rounded-lg border
               border-primary/30 bg-card px-4 py-3 shadow-lg"
        role="status"
        aria-live="polite"
      >
        <div class="flex-1">
          <p class="text-sm font-medium text-foreground">Update available</p>
          <p class="text-xs text-muted-foreground">{{ updateVersion() }} is ready to install.</p>
        </div>
        <button
          (click)="installUpdate()"
          class="btn-primary text-xs px-3 py-1.5"
          [disabled]="installing()"
        >
          {{ installing() ? 'Installing...' : 'Install' }}
        </button>
        <button
          (click)="dismissUpdate()"
          class="text-muted-foreground hover:text-foreground transition-colors"
          aria-label="Dismiss update notification"
        >
          &times;
        </button>
      </div>
    }
  `,
})
export class UpdateCheckerComponent implements OnInit {
  private readonly tauriDetection = inject(TauriDetectionService);

  protected readonly updateAvailable = signal(false);
  protected readonly updateVersion = signal<string>('');
  protected readonly installing = signal(false);

  // Store the updater object for later installation
  private updaterRef: unknown = null;

  ngOnInit(): void {
    if (this.tauriDetection.isTauri()) {
      this.checkForUpdates();
    }
  }

  private async checkForUpdates(): Promise<void> {
    try {
      // Dynamic import to avoid errors outside Tauri.
      // @tauri-apps/plugin-updater is only available in the bundled Tauri app.
      // We use Function() constructor to bypass TypeScript's static module analysis.
      // eslint-disable-next-line @typescript-eslint/no-implied-eval, no-new-func
      const dynamicImport = new Function('modulePath', 'return import(modulePath)') as (p: string) => Promise<Record<string, unknown>>;
      const updaterModule = await dynamicImport('@tauri-apps/plugin-updater');
      const check = updaterModule['check'] as () => Promise<{ available: boolean; version?: string } | null>;
      const update = await check();
      if (update?.available) {
        this.updaterRef = update;
        this.updateVersion.set(update.version ?? 'New version');
        this.updateAvailable.set(true);
      }
    } catch {
      // Not in Tauri or plugin not available — silently ignore
    }
  }

  protected async installUpdate(): Promise<void> {
    if (!this.updaterRef || this.installing()) return;
    this.installing.set(true);
    try {
      const updater = this.updaterRef as { downloadAndInstall: () => Promise<void> };
      await updater.downloadAndInstall();
      // Tauri will restart the app after installation
    } catch (err) {
      console.error('[shell] Update installation failed:', err);
      this.installing.set(false);
    }
  }

  protected dismissUpdate(): void {
    this.updateAvailable.set(false);
  }
}
