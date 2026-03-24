/**
 * AppComponent — Shell root layout component.
 *
 * Orchestrates the full application layout:
 *   Header | SidebarShell (sidebar-remote) | Main (chat-remote) | SettingsFlyout | OnboardingGate | UpdateChecker
 *
 * Remote components are loaded via RemoteLoaderService wrapping Native Federation.
 * Chat and sidebar are loaded eagerly on init (always visible).
 * Settings flyout is loaded lazily when appStore.settingsFlyoutOpen() becomes true.
 */
import {
  ChangeDetectionStrategy,
  Component,
  Injector,
  NgZone,
  OnInit,
  Type,
  inject,
  signal,
} from '@angular/core';
import { NgComponentOutlet } from '@angular/common';
import { AppStore } from '@shipagent/shared-state';
import { RemoteLoaderService } from './remote-loader.service';
import { HeaderComponent } from './header/header.component';
import { SidebarShellComponent } from './sidebar-shell/sidebar-shell.component';
import { OnboardingGateComponent } from './onboarding-gate/onboarding-gate.component';
import { UpdateCheckerComponent } from './update-checker/update-checker.component';

@Component({
  selector: 'app-root',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NgComponentOutlet,
    HeaderComponent,
    SidebarShellComponent,
    OnboardingGateComponent,
    UpdateCheckerComponent,
  ],
  template: `
    <div class="h-screen flex flex-col bg-background overflow-hidden">
      <!-- Global header -->
      <app-header />

      <!-- Body: sidebar + main -->
      <div class="flex-1 flex overflow-hidden relative">

        <!-- Collapsible sidebar hosting sidebar-remote -->
        <app-sidebar-shell [collapsed]="appStore.sidebarCollapsed()">
          @if (sidebarComponent()) {
            <ng-container
              [ngComponentOutlet]="sidebarComponent()!"
              [ngComponentOutletInjector]="sidebarInjector()!"
            />
          }
        </app-sidebar-shell>

        <!-- Main content hosting chat-remote -->
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

      <!-- Settings flyout — loaded lazily when open -->
      @if (appStore.settingsFlyoutOpen() && settingsComponent()) {
        <ng-container
          [ngComponentOutlet]="settingsComponent()!"
          [ngComponentOutletInjector]="settingsInjector()!"
        />
      }

      <!-- Onboarding gate — overlays full screen on first launch -->
      <app-onboarding-gate />

      <!-- Update checker — only active inside Tauri -->
      <app-update-checker />
    </div>
  `,
})
export class AppComponent implements OnInit {
  protected readonly appStore = inject(AppStore);
  private readonly remoteLoader = inject(RemoteLoaderService);
  private readonly injector = inject(Injector);
  private readonly ngZone = inject(NgZone);

  // Remote component types (null = not yet loaded)
  protected readonly chatComponent = signal<Type<unknown> | null>(null);
  protected readonly sidebarComponent = signal<Type<unknown> | null>(null);
  protected readonly settingsComponent = signal<Type<unknown> | null>(null);

  // Child injectors scoping remote providers
  protected readonly chatInjector = signal<Injector>(this.injector);
  protected readonly sidebarInjector = signal<Injector>(this.injector);
  protected readonly settingsInjector = signal<Injector>(this.injector);

  ngOnInit(): void {
    // Eagerly load chat and sidebar (always visible)
    this.loadChatRemote();
    this.loadSidebarRemote();

    // Lazily load settings flyout when first opened
    this.watchSettingsFlyout();
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
      if (!loaded && this.appStore.settingsFlyoutOpen()) {
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
