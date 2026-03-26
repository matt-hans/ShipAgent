/**
 * RemoteLoaderService — Wraps Native Federation's loadRemoteModule for all 4
 * remotes (chat, sidebar, settings, domain).
 *
 * Each load method returns the component type (and any providers) required
 * to dynamically render the remote using NgComponentOutlet.
 *
 * Remotes are loaded lazily on first request; subsequent calls hit the module
 * federation cache automatically.
 */
import { Injectable, Type } from '@angular/core';
import { loadRemoteModule } from '@angular-architects/native-federation';

/** Minimal shape of a resolved remote entry. */
export interface RemoteEntry {
  /** The standalone Angular component to render. */
  component: Type<unknown>;
  /** Optional root-level providers to scope to the remote injector. */
  providers?: Array<unknown>;
}

@Injectable({ providedIn: 'root' })
export class RemoteLoaderService {
  /**
   * Load the ChatContainer component from the chat-remote.
   * Exposes: './ChatContainer'
   */
  async loadChat(): Promise<RemoteEntry> {
    const m = await loadRemoteModule('chat-remote', './ChatContainer');
    // Support both a named remoteEntry export and a direct component export.
    return (m['remoteEntry'] as RemoteEntry | undefined) ?? {
      component: m['ChatContainerComponent'] as Type<unknown>,
    };
  }

  /**
   * Load the SidebarContent component from the sidebar-remote.
   * Exposes: './SidebarContent'
   */
  async loadSidebar(): Promise<RemoteEntry> {
    const m = await loadRemoteModule('sidebar-remote', './SidebarContent');
    return (m['remoteEntry'] as RemoteEntry | undefined) ?? {
      component: m['SidebarContentComponent'] as Type<unknown>,
    };
  }

  /**
   * Load the SettingsFlyout component from the settings-remote.
   * Exposes: './SettingsFlyout'
   */
  async loadSettingsFlyout(): Promise<RemoteEntry> {
    const m = await loadRemoteModule('settings-remote', './SettingsFlyout');
    return (m['remoteEntry'] as RemoteEntry | undefined) ?? {
      component: m['SettingsFlyoutComponent'] as Type<unknown>,
    };
  }

  /**
   * Load the OnboardingWizard component from the settings-remote.
   * Exposes: './OnboardingWizard'
   *
   * Note: We access OnboardingWizardComponent directly instead of using
   * m.remoteEntry because remoteEntry always points to SettingsFlyoutComponent.
   */
  async loadOnboardingWizard(): Promise<RemoteEntry> {
    const m = await loadRemoteModule('settings-remote', './OnboardingWizard');
    return { component: m['OnboardingWizardComponent'] as Type<unknown> };
  }

  /**
   * Load the DomainCardRegistry service from the domain-remote.
   * Exposes: './DomainCardRegistry'
   */
  async loadDomainCardRegistry(): Promise<unknown> {
    const m = await loadRemoteModule('domain-remote', './DomainCardRegistry');
    return (m['DomainCardRegistryService'] as unknown) ?? (m['default'] as unknown);
  }
}
