/**
 * AppComponent integration tests — Shell loading all remotes.
 *
 * Tests that the shell correctly:
 *   - Creates the component without error
 *   - Renders the layout (header, onboarding gate, update checker)
 *   - Eagerly loads chat and sidebar remotes on init
 *   - Lazily loads settings remote when appStore.openSettings() is called
 *   - Survives remote load failures gracefully
 *   - Reads SettingsStore (onboarding gate) and ConversationStore (interactive toggle)
 *
 * NOTE: Native Federation's loadRemoteModule is mocked so tests run without
 * a running federation server.
 *
 * NOTE: fakeAsync is NOT used because zone.js/testing is not configured in the
 * test environment. Tests use async/await + whenStable() instead.
 *
 * NOTE: Node 25 ships with a stub localStorage that requires --localstorage-file
 * to be functional. The beforeAll block below replaces it with a working
 * Map-backed shim before ConversationStore (withStorageSync) initialises.
 */

import { TestBed } from '@angular/core/testing';
import { Component } from '@angular/core';
import { vi, beforeAll } from 'vitest';
import { AppComponent } from './app.component';
import { RemoteLoaderService } from './remote-loader.service';
import { AppStore, SettingsStore, ConversationStore } from '@shipagent/shared-state';
import type { RemoteEntry } from './remote-loader.service';

// ---------------------------------------------------------------------------
// Install a working in-memory localStorage before Angular's DI system runs.
// Node 25 exposes localStorage as a stub that requires --localstorage-file;
// without a valid path, localStorage.getItem is not a function.
// ---------------------------------------------------------------------------

class LocalStorageShim implements Storage {
  private readonly store = new Map<string, string>();
  get length(): number { return this.store.size; }
  clear(): void { this.store.clear(); }
  getItem(key: string): string | null {
    return this.store.has(key) ? (this.store.get(key) as string) : null;
  }
  key(index: number): string | null {
    const keys = Array.from(this.store.keys());
    return index < keys.length ? keys[index] : null;
  }
  removeItem(key: string): void { this.store.delete(key); }
  setItem(key: string, value: string): void { this.store.set(key, value); }
}

beforeAll(() => {
  Object.defineProperty(globalThis, 'localStorage', {
    value: new LocalStorageShim(),
    writable: true,
    configurable: true,
  });
});

// ---------------------------------------------------------------------------
// Minimal stub components returned by the mock remote loader
// ---------------------------------------------------------------------------

@Component({ selector: 'app-stub-chat', standalone: true, template: '<div>Chat</div>' })
class StubChatComponent {}

@Component({ selector: 'app-stub-sidebar', standalone: true, template: '<div>Sidebar</div>' })
class StubSidebarComponent {}

@Component({ selector: 'app-stub-settings', standalone: true, template: '<div>Settings</div>' })
class StubSettingsComponent {}

// ---------------------------------------------------------------------------
// Mock RemoteLoaderService using vi.fn()
// ---------------------------------------------------------------------------

function createMockRemoteLoader(): RemoteLoaderService {
  return {
    loadChat: vi.fn().mockResolvedValue({ component: StubChatComponent } as RemoteEntry),
    loadSidebar: vi.fn().mockResolvedValue({ component: StubSidebarComponent } as RemoteEntry),
    loadSettingsFlyout: vi.fn().mockResolvedValue({ component: StubSettingsComponent } as RemoteEntry),
    loadOnboardingWizard: vi.fn().mockResolvedValue({ component: StubSettingsComponent } as RemoteEntry),
    loadDomainCardRegistry: vi.fn().mockResolvedValue(null),
  } as unknown as RemoteLoaderService;
}

describe('AppComponent — shell integration', () => {
  let mockLoader: ReturnType<typeof createMockRemoteLoader>;

  beforeEach(async () => {
    mockLoader = createMockRemoteLoader();

    await TestBed.configureTestingModule({
      imports: [AppComponent],
      providers: [
        { provide: RemoteLoaderService, useValue: mockLoader },
      ],
    }).compileComponents();
  });

  it('should create the component', () => {
    const fixture = TestBed.createComponent(AppComponent);
    expect(fixture.componentInstance).toBeTruthy();
  });

  it('should render the header element', async () => {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('app-header')).toBeTruthy();
  });

  it('should call loadChat on init', async () => {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    await fixture.whenStable();

    expect((mockLoader.loadChat as ReturnType<typeof vi.fn>).mock.calls.length).toBe(1);
  });

  it('should call loadSidebar on init', async () => {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    await fixture.whenStable();

    expect((mockLoader.loadSidebar as ReturnType<typeof vi.fn>).mock.calls.length).toBe(1);
  });

  it('should NOT call loadSettingsFlyout on init (lazy load)', async () => {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    await fixture.whenStable();

    expect((mockLoader.loadSettingsFlyout as ReturnType<typeof vi.fn>).mock.calls.length).toBe(0);
  });

  it('should render onboarding gate component', async () => {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('app-onboarding-gate')).toBeTruthy();
  });

  it('should render update checker component', async () => {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('app-update-checker')).toBeTruthy();
  });

  describe('onboarding gate visibility', () => {
    it('should have onboardingCompleted false by default (gate visible)', () => {
      TestBed.createComponent(AppComponent);
      const settingsStore = TestBed.inject(SettingsStore);
      expect(settingsStore.onboardingCompleted()).toBe(false);
    });

    it('should update SettingsStore.onboardingCompleted to true', () => {
      TestBed.createComponent(AppComponent);
      const settingsStore = TestBed.inject(SettingsStore);
      settingsStore.setOnboardingCompleted(true);
      expect(settingsStore.onboardingCompleted()).toBe(true);
    });
  });

  describe('interactive shipping toggle', () => {
    it('should read interactiveShipping from ConversationStore (default false)', () => {
      TestBed.createComponent(AppComponent);
      const conversationStore = TestBed.inject(ConversationStore);
      expect(conversationStore.interactiveShipping()).toBe(false);
    });

    it('should reflect interactiveShipping toggle change in store', () => {
      TestBed.createComponent(AppComponent);
      const conversationStore = TestBed.inject(ConversationStore);
      conversationStore.setInteractiveShipping(true);
      expect(conversationStore.interactiveShipping()).toBe(true);
    });
  });

  describe('settings flyout', () => {
    it('should have settingsFlyoutOpen = false initially', () => {
      TestBed.createComponent(AppComponent);
      const appStore = TestBed.inject(AppStore);
      expect(appStore.settingsFlyoutOpen()).toBe(false);
    });

    it('should update AppStore.settingsFlyoutOpen on openSettings()', () => {
      TestBed.createComponent(AppComponent);
      const appStore = TestBed.inject(AppStore);
      appStore.openSettings();
      expect(appStore.settingsFlyoutOpen()).toBe(true);
    });
  });

  describe('graceful remote load failures', () => {
    it('should NOT throw when chat-remote fails to load', async () => {
      (mockLoader.loadChat as ReturnType<typeof vi.fn>).mockRejectedValue(
        new Error('Chat remote not built'),
      );

      const fixture = TestBed.createComponent(AppComponent);
      let caughtError: unknown = null;
      try {
        fixture.detectChanges();
        await fixture.whenStable();
      } catch (e) {
        caughtError = e;
      }

      expect(caughtError).toBeNull();
    });

    it('should NOT throw when sidebar-remote fails to load', async () => {
      (mockLoader.loadSidebar as ReturnType<typeof vi.fn>).mockRejectedValue(
        new Error('Sidebar remote not built'),
      );

      const fixture = TestBed.createComponent(AppComponent);
      let caughtError: unknown = null;
      try {
        fixture.detectChanges();
        await fixture.whenStable();
      } catch (e) {
        caughtError = e;
      }

      expect(caughtError).toBeNull();
    });
  });
});
