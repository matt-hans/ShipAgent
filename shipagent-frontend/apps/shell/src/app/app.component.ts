/**
 * AppComponent — Shell root layout component.
 *
 * Orchestrates the full application layout:
 *   Header | SidebarShell (sidebar-remote) | Main (chat-remote) | SettingsFlyout | OnboardingGate | UpdateChecker
 *
 * Remote components are loaded via RemoteLoaderService wrapping Native Federation.
 * Chat and sidebar load only after the browser API session and settings check.
 * Settings flyout is loaded lazily when appStore.settingsFlyoutOpen() becomes true.
 */
import {
  ChangeDetectionStrategy,
  Component,
  Injector,
  NgZone,
  OnInit,
  Type,
  effect,
  inject,
  signal,
} from '@angular/core';
import { NgComponentOutlet } from '@angular/common';
import { finalize } from 'rxjs';
import { AppStore, SettingsStore } from '@shipagent/shared-state';
import {
  ApiError,
  ApiService,
  BrowserSessionState,
} from '@shipagent/shared-api';
import type { BrowserSessionStatus } from '@shipagent/shared-types';
import { RemoteLoaderService } from './remote-loader.service';
import { ApiKeyGateComponent } from './api-key-gate/api-key-gate.component';
import { HeaderComponent } from './header/header.component';
import { SidebarShellComponent } from './sidebar-shell/sidebar-shell.component';
import { OnboardingGateComponent } from './onboarding-gate/onboarding-gate.component';
import { UpdateCheckerComponent } from './update-checker/update-checker.component';

type AuthState = 'checking' | 'required' | 'ready' | 'error';

@Component({
  selector: 'app-root',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NgComponentOutlet,
    ApiKeyGateComponent,
    HeaderComponent,
    SidebarShellComponent,
    OnboardingGateComponent,
    UpdateCheckerComponent,
  ],
  template: `
    @if (authState() === 'checking') {
      <main
        class="h-screen bg-background flex flex-col items-center justify-center gap-4"
        role="status"
        aria-live="polite"
      >
        <div
          class="h-10 w-10 animate-spin rounded-full border-4 border-primary border-t-transparent"
          aria-hidden="true"
        ></div>
        <p class="text-sm text-muted-foreground">Checking API session…</p>
      </main>
    } @else if (authState() === 'error') {
      <main
        class="h-screen bg-background flex flex-col items-center justify-center gap-4 p-6 text-center"
      >
        <h1 class="text-xl font-semibold text-foreground">
          ShipAgent could not reach the API
        </h1>
        <p class="max-w-md text-sm text-muted-foreground">
          Check that the backend is running, then retry the session check.
        </p>
        <button
          type="button"
          class="btn-primary rounded-lg px-5 py-2"
          (click)="checkBrowserSession()"
        >
          Retry connection
        </button>
      </main>
    } @else if (authState() === 'required') {
      <app-api-key-gate
        (authenticated)="onSessionAuthenticated()"
      />
    } @else {
      <div class="h-screen flex flex-col bg-background overflow-hidden">
        <app-header
          [showApiSessionControl]="sessionRequired()"
          [clearingApiSession]="clearingSession()"
          (clearApiSession)="clearBrowserSession()"
        />

        @if (clearSessionFailed()) {
          <div
            role="alert"
            class="border-b border-destructive/30 bg-destructive/10 px-4 py-2 text-center text-sm text-destructive"
          >
            The API session could not be cleared. Try again.
          </div>
        }

        <div class="flex-1 flex overflow-hidden relative">
          <app-sidebar-shell [collapsed]="appStore.sidebarCollapsed()">
            @if (sidebarComponent()) {
              <ng-container
                [ngComponentOutlet]="sidebarComponent()!"
                [ngComponentOutletInjector]="sidebarInjector()!"
              />
            }
          </app-sidebar-shell>

          <main class="flex-1 flex flex-col overflow-hidden">
            @if (chatComponent()) {
              <ng-container
                [ngComponentOutlet]="chatComponent()!"
                [ngComponentOutletInjector]="chatInjector()!"
              />
            } @else {
              <div class="flex-1 flex items-center justify-center text-muted-foreground text-sm">
                Loading command center...
              </div>
            }
          </main>
        </div>

        @if (appStore.settingsFlyoutOpen() && settingsComponent()) {
          <ng-container
            [ngComponentOutlet]="settingsComponent()!"
            [ngComponentOutletInjector]="settingsInjector()!"
          />
        }

        <app-onboarding-gate />
        <app-update-checker />
      </div>
    }
  `,
})
export class AppComponent implements OnInit {
  protected readonly appStore = inject(AppStore);
  private readonly settingsStore = inject(SettingsStore);
  private readonly apiService = inject(ApiService);
  private readonly remoteLoader = inject(RemoteLoaderService);
  private readonly injector = inject(Injector);
  private readonly ngZone = inject(NgZone);
  private readonly browserSession = inject(BrowserSessionState);

  protected readonly authState = signal<AuthState>('checking');
  protected readonly sessionRequired = signal(false);
  protected readonly clearingSession = signal(false);
  protected readonly clearSessionFailed = signal(false);

  // Remote component types (null = not yet loaded)
  protected readonly chatComponent = signal<Type<unknown> | null>(null);
  protected readonly sidebarComponent = signal<Type<unknown> | null>(null);
  protected readonly settingsComponent = signal<Type<unknown> | null>(null);

  // Child injectors scoping remote providers
  protected readonly chatInjector = signal<Injector>(this.injector);
  protected readonly sidebarInjector = signal<Injector>(this.injector);
  protected readonly settingsInjector = signal<Injector>(this.injector);

  private applicationInitialized = false;
  private settingsWatcherStarted = false;
  private handledExpirationVersion = 0;

  constructor() {
    effect(() => {
      const expirationVersion = this.browserSession.expirationVersion();
      if (expirationVersion <= this.handledExpirationVersion) return;

      this.handledExpirationVersion = expirationVersion;
      this.sessionRequired.set(true);
      this.requireAuthentication();
    });
  }

  ngOnInit(): void {
    this.checkBrowserSession();
  }

  protected checkBrowserSession(): void {
    this.authState.set('checking');
    this.apiService.getBrowserSessionStatus().subscribe({
      next: (status) => this.applySessionStatus(status),
      error: () => this.authState.set('error'),
    });
  }

  protected onSessionAuthenticated(): void {
    this.checkBrowserSession();
  }

  protected clearBrowserSession(): void {
    if (this.clearingSession()) return;

    this.clearingSession.set(true);
    this.clearSessionFailed.set(false);
    this.apiService
      .clearBrowserSession()
      .pipe(finalize(() => this.clearingSession.set(false)))
      .subscribe({
        next: (status) => {
          this.applicationInitialized = false;
          this.settingsStore.setAppSettings(null);
          this.applySessionStatus(status);
        },
        error: () => this.clearSessionFailed.set(true),
      });
  }

  private applySessionStatus(status: BrowserSessionStatus): void {
    this.sessionRequired.set(status.required);
    this.clearSessionFailed.set(false);
    if (status.required && !status.authenticated) {
      this.requireAuthentication();
      return;
    }

    this.authState.set('ready');
    this.initializeAuthenticatedApplication();
  }

  private initializeAuthenticatedApplication(): void {
    if (this.applicationInitialized) return;
    this.applicationInitialized = true;

    this.apiService.getSettings().subscribe({
      next: (settings) => {
        this.settingsStore.setAppSettings(settings);
        if (!this.chatComponent()) this.loadChatRemote();
        if (!this.sidebarComponent()) this.loadSidebarRemote();
        if (!this.settingsWatcherStarted) {
          this.settingsWatcherStarted = true;
          this.watchSettingsFlyout();
        }
      },
      error: (error: unknown) => {
        this.applicationInitialized = false;
        if (error instanceof ApiError && error.statusCode === 401) {
          this.requireAuthentication();
          return;
        }
        this.authState.set('error');
      },
    });
  }

  private requireAuthentication(): void {
    this.applicationInitialized = false;
    this.settingsStore.setAppSettings(null);
    this.appStore.closeSettings();
    this.clearSessionFailed.set(false);
    this.authState.set('required');
  }

  private async loadChatRemote(): Promise<void> {
    try {
      const entry = await this.remoteLoader.loadChat();
      const childInjector = entry.providers?.length
        ? Injector.create({
            providers: entry.providers as Parameters<typeof Injector.create>[0]['providers'],
            parent: this.injector,
          })
        : this.injector;
      this.ngZone.run(() => {
        this.chatInjector.set(childInjector);
        this.chatComponent.set(entry.component);
      });
    } catch (err) {
      // Remote not built yet — shell still renders without it
      console.warn('[shell] chat-remote not available:', err);
    }
  }

  private async loadSidebarRemote(): Promise<void> {
    try {
      const entry = await this.remoteLoader.loadSidebar();
      const childInjector = entry.providers?.length
        ? Injector.create({
            providers: entry.providers as Parameters<typeof Injector.create>[0]['providers'],
            parent: this.injector,
          })
        : this.injector;
      this.ngZone.run(() => {
        this.sidebarInjector.set(childInjector);
        this.sidebarComponent.set(entry.component);
      });
    } catch (err) {
      console.warn('[shell] sidebar-remote not available:', err);
    }
  }

  private watchSettingsFlyout(): void {
    // Use requestAnimationFrame polling to detect when settings flyout opens.
    // This avoids injecting EffectRef outside injection context.
    // The settings remote is loaded at most once per session.
    let loaded = false;
    const poll = (): void => {
      if (
        !loaded &&
        this.authState() === 'ready' &&
        this.appStore.settingsFlyoutOpen()
      ) {
        loaded = true; // prevent concurrent loads
        this.loadSettingsRemote();
      }
      requestAnimationFrame(poll);
    };
    requestAnimationFrame(poll);
  }

  private async loadSettingsRemote(): Promise<void> {
    try {
      const entry = await this.remoteLoader.loadSettingsFlyout();
      const childInjector = entry.providers?.length
        ? Injector.create({
            providers: entry.providers as Parameters<typeof Injector.create>[0]['providers'],
            parent: this.injector,
          })
        : this.injector;
      this.ngZone.run(() => {
        this.settingsInjector.set(childInjector);
        this.settingsComponent.set(entry.component);
      });
    } catch (err) {
      console.warn('[shell] settings-remote not available:', err);
    }
  }
}
