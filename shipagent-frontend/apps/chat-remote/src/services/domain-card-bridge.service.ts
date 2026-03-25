/**
 * DomainCardBridgeService — Cross-remote bridge to domain-remote's card registry.
 *
 * Chat-remote must NEVER import domain-remote directly. This service bridges
 * the two remotes by loading domain-remote's DomainCardRegistryService via the
 * shell's RemoteLoaderService (which uses loadRemoteModule under the hood).
 *
 * ARCHITECTURE: The shell's RemoteLoaderService is available in the Angular DI
 * tree when chat-remote is hosted by the shell. Chat-container passes the
 * injector to this service; we use it to dynamically resolve RemoteLoaderService
 * at runtime (avoiding a static cross-app import that would break federation).
 *
 * Usage:
 *   - Call initialize(injector) in ChatContainerComponent.ngOnInit()
 *   - Use resolve(cardType) to get a Component Type for ngComponentOutlet
 *
 * Provided at component level (not root).
 */

import { Injectable, signal, Type, Injector } from '@angular/core';
import { loadRemoteModule } from '@angular-architects/native-federation';

/** Minimal interface for the domain-remote DomainCardRegistryService. */
interface DomainCardRegistry {
  resolve(cardType: string): Type<unknown> | null;
}

@Injectable()
export class DomainCardBridgeService {
  /** The loaded registry service instance from domain-remote. */
  private readonly registrySignal = signal<DomainCardRegistry | null>(null);

  /** Whether the registry has been loaded. */
  readonly isLoaded = signal(false);

  /**
   * Asynchronously load DomainCardRegistryService from domain-remote via
   * Native Federation's loadRemoteModule. This avoids any static import
   * of domain-remote — the bridge is purely runtime-resolved.
   *
   * Safe to call multiple times — returns immediately if already loaded.
   */
  async initialize(_injector?: Injector): Promise<void> {
    if (this.isLoaded()) return;

    try {
      const m = await loadRemoteModule('domain-remote', './DomainCardRegistry');
      // Prefer the named export, fall back to default.
      const RegistryClass = m['DomainCardRegistryService'] ?? m['default'];

      if (RegistryClass) {
        // DomainCardRegistryService is a plain class — instantiate it directly.
        // It does not need Angular DI (it is a pure registry map, not a service with deps).
        const instance = new RegistryClass() as DomainCardRegistry;
        if (typeof instance.resolve === 'function') {
          this.registrySignal.set(instance);
          this.isLoaded.set(true);
        }
      }
    } catch (err) {
      // Domain remote may not be available in all environments.
      // Chat UI still works without domain cards.
      console.warn('[DomainCardBridgeService] Failed to load domain card registry:', err);
    }
  }

  /**
   * Resolve a domain card component type by event type string.
   * Returns null if registry not loaded or card type not found.
   *
   * @param cardType The SSE event type (e.g., 'tracking_result', 'pickup_result').
   */
  resolve(cardType: string): Type<unknown> | null {
    const registry = this.registrySignal();
    if (!registry) return null;
    return registry.resolve(cardType);
  }
}
